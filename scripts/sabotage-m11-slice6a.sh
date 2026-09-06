#!/usr/bin/env bash
# Negative controls for M11 slice 6A — bounded checksum verification.
#
# §19 :1318's rule is that a maintenance job must be bounded. Controls 1 and 2 attack the bound
# from both sides: removing it, and keeping it while lying about what it left unchecked. Controls
# 4 and 5 attack the other half of the claim — that the job reports and never repairs.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

VERIFY=services/backend/app/storage/verification.py
BEAT=services/backend/app/workers/celery_app.py

BACKUP=$(mktemp -d)
cp "$VERIFY" "$BACKUP/verification.py"
cp "$BEAT" "$BACKUP/celery_app.py"

restore() {
  cp "$BACKUP/verification.py" "$VERIFY"
  cp "$BACKUP/celery_app.py" "$BEAT"
}
trap restore EXIT

SUITE="tests/integration/test_checksum_verification.py"

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
$PY -m pytest $SUITE tests/backend -q --no-header 2>&1 | tail -3

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if $PY -m pytest $SUITE tests/backend -q --no-header >"$BACKUP/out.txt" 2>&1; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT: $(grep -c '^FAILED' "$BACKUP/out.txt") failing"
    grep '^FAILED' "$BACKUP/out.txt" | head -4
  fi
  restore
}

# 1. The limit is dropped, so the pass reads every row. This is the failure §19 names: a job that
#    takes longer every night until it stops finishing.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/storage/verification.py")
s = p.read_text()
s = s.replace("                .limit(limit)\n", "")
p.write_text(s)
EOF
probe "1. the pass is unbounded"

# 2. The bound stays but `remaining` is always zero, so a partial pass reads as full coverage.
#    Subtler than control 1 and worse: nothing looks wrong.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/storage/verification.py")
s = p.read_text()
s = s.replace("        remaining=max(total - len(rows), 0),", "        remaining=0,")
p.write_text(s)
EOF
probe "2. a partial pass claims full coverage"

# 3. A limit of zero is accepted, which is an unbounded pass spelled as a bounded one.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/storage/verification.py")
s = p.read_text()
s = s.replace(
    '    if limit < 1:\n'
    '        raise ValueError("a checksum pass with no limit would be unbounded, which §19 forbids")\n',
    "",
)
p.write_text(s)
EOF
probe "3. a limit below one is accepted"

# 4. The job "repairs" what it finds by writing the measured digest over the recorded one. This is
#    the tempting fix and it destroys the only evidence that anything disagreed.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/storage/verification.py")
s = p.read_text()
s = s.replace(
    "        uow.rollback()\n",
    "        uow.rollback()\n"
    "    from sqlalchemy import update as _u\n"
    "    with runtime.uow_factory() as _fix:\n"
    "        for _id, _k, _d, _z in rows:\n"
    "            _m = storage.stat(_k)\n"
    "            if _m is not None and _m.sha256_hash != _d:\n"
    "                _fix.session.execute(\n"
    "                    _u(FileObject).where(FileObject.id == _id)\n"
    "                    .values(sha256_hash=_m.sha256_hash)\n"
    "                )\n"
    "        _fix.commit()\n",
)
p.write_text(s)
EOF
probe "4. the job rewrites the recorded digest to match the bytes"

# 5. A mismatch stops being reported at all, so the job runs nightly and finds nothing.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/storage/verification.py")
s = p.read_text()
s = s.replace(
    "        if measured.sha256_hash != recorded_digest or measured.size_bytes != recorded_size:",
    "        if False:",
)
p.write_text(s)
EOF
probe "5. no mismatch is ever reported"

# 6. Size is no longer compared.
#
# **Expected NOT CAUGHT, and the reason is worth keeping.** Any change to the bytes changes the
# digest, so every case where the size disagrees is already a case where the digest disagrees.
# The size comparison cannot fail on its own without a sha256 collision, which is not a scenario a
# test can construct. It is defence in depth and free — the object has already been read — but it
# is not load-bearing, and a control that claimed to prove it would be claiming more than it does.
#
# This is the third redundant guard this project has found by running a control against it; the
# first two were slice 3B's sent-timestamp and its status filter. Kept as a control so that the
# day the check *does* become load-bearing — a storage backend reporting size without hashing,
# say — this starts failing and says so.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/storage/verification.py")
s = p.read_text()
s = s.replace(
    "        if measured.sha256_hash != recorded_digest or measured.size_bytes != recorded_size:",
    "        if measured.sha256_hash != recorded_digest:",
)
p.write_text(s)
EOF
probe "6. size is no longer compared"

# 7. The schedule entry is removed, so the job exists and nothing runs it — the shape this whole
#    slice exists to fix.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/workers/celery_app.py")
s = p.read_text()
start = s.find('    "checksum-verification": {')
end = s.find("    },\n", start) + len("    },\n")
p.write_text(s[:start] + s[end:])
EOF
probe "7. the job has no caller again"

echo
echo "=== restored ==="
git status --short
