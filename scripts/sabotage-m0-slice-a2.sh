#!/usr/bin/env bash
# Negative controls for M0 slice A2 — the second human's step-up, and the read chain behind it.
#
# The slice adds a security control, so most controls here switch a binding off one at a time.
# `step_up.rejection_for` compares four things and this slice adds a fifth reading of the first;
# a control per binding is the only way to know each is load-bearing rather than incidentally
# satisfied by the others.
#
# Controls 6 and 7 attack the reads instead, and 8 attacks the gate that found them.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.
#
# **Write the transcript somewhere that survives.** The first full run of this script was captured
# to `/tmp`, which was cleared before the last control's result could be read — 17 minutes of work
# gone, and no way to tell whether control 8 had caught anything. `RUN_LOG` defaults beside the
# repository instead. The tree was restored correctly, which is the part that matters and is worth
# checking anyway: `trap restore EXIT` does not fire if the shell is killed.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

RUN_LOG="${RUN_LOG:-$HOME/slice-a2-controls.txt}"
exec > >(tee "$RUN_LOG") 2>&1
echo "transcript: $RUN_LOG"

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

STEPUP=services/backend/app/security/step_up.py
COMMAND=services/backend/app/commands/publication_correction.py
ROUTE=services/backend/app/api/v1/payment_publications.py
AUTH=services/backend/app/api/v1/auth.py
LINKS=services/backend/app/api/v1/evidence_links.py
SEGMENTS=services/backend/app/api/v1/receipt_segments.py

BACKUP=$(mktemp -d)
for file in "$STEPUP" "$COMMAND" "$ROUTE" "$AUTH" "$LINKS" "$SEGMENTS"; do
  cp "$file" "$BACKUP/$(basename "$file")"
done

restore() {
  for file in "$STEPUP" "$COMMAND" "$ROUTE" "$AUTH" "$LINKS" "$SEGMENTS"; do
    cp "$BACKUP/$(basename "$file")" "$file"
  done
}
trap restore EXIT

SUITE="tests/integration/test_publication_correction.py \
tests/integration/test_evidence_links.py \
tests/integration/test_segment_intake.py \
tests/backend"

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
$PY -m pytest -c services/backend/pyproject.toml $SUITE -q --no-header 2>&1 | tail -3

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if $PY -m pytest -c services/backend/pyproject.toml $SUITE -q --no-header >"$BACKUP/out.txt" 2>&1; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT: $(grep -c '^FAILED' "$BACKUP/out.txt") failing"
    grep '^FAILED' "$BACKUP/out.txt" | head -5
  fi
  restore
}

# 1. The header stops being required. The route reverts to what it was for two milestones: a
#    dual-control command a preparer can complete by knowing a manager's user id.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/payment_publications.py")
s = p.read_text()
before = s
s = s.replace(
    '    if recent_auth is None:\n        raise PreconditionRequiredError("X-Recent-Auth")\n',
    '    recent_auth = recent_auth or ""\n',
)
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "1. the correction no longer requires a step-up"

# 2. The actor binding goes. **The control's centre**: with it, *any* valid context authorises the
#    correction — including one the preparer obtained for themselves, which is the case the whole
#    mechanism exists to refuse.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/security/step_up.py")
s = p.read_text()
before = s
s = s.replace(
    "    if stored.actor_id != (actor.actor_id if on_behalf_of is None else on_behalf_of):\n"
    "        return StepUpRejection.WRONG_ACTOR\n",
    "",
)
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "2. any actor's step-up authorises the correction"

# 3. Subtler than 2 and the more likely mistake: `on_behalf_of` is accepted and ignored, so the
#    comparison silently falls back to the caller. Every existing step-up test still passes,
#    because every *other* caller passes `None`.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/security/step_up.py")
s = p.read_text()
before = s
s = s.replace(
    "    if stored.actor_id != (actor.actor_id if on_behalf_of is None else on_behalf_of):",
    "    if stored.actor_id != actor.actor_id:",
)
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "3. on_behalf_of is accepted and ignored"

# 4. The **session** binding goes, and this is the one that would not look like a bug. The
#    approver's identity is still checked; what is lost is "at this machine, during this sitting",
#    so a reference obtained anywhere becomes spendable here — a manager approving by message.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/security/step_up.py")
s = p.read_text()
before = s
s = s.replace(
    "    if stored.session_id != actor.session_id:\n"
    "        return StepUpRejection.WRONG_SESSION\n",
    "",
)
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "4. a step-up from any session is accepted"

# 5. The reference is never spent, so one manager's password authorises every correction that
#    follows. Nothing observable changes on the first call, which is the point.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/commands/publication_correction.py")
s = p.read_text()
before = s
s = s.replace(
    "    stored.consumed_at = now\n    stored.consumed_by_command = CORRECT_OPERATION",
    "    pass",
)
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "5. a recent-auth reference can be spent twice"

# 6. The step-up route stops checking the approver's password — it resolves the username and issues
#    a context regardless. The correction then succeeds for a preparer who knows a manager's name.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/auth.py")
s = p.read_text()
before = s
s = s.replace(
    "            if refused is None and not verification.is_valid:\n"
    '                refused = "wrong_password"\n',
    "",
)
assert s != before, "control 6 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "6. the approver's password is not checked"

# 7. The evidence link read loses its guard, so anybody with a session can see which segment proves
#    a payment. A read this slice added is a read this slice owes a negative for.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/evidence_links.py")
s = p.read_text()
before = s
s = s.replace(
    '    operation_id="getEvidenceLink",\n'
    '    summary="One confirmed evidence link, so a screen can resolve what a publication cites.",\n'
    "    responses=RESPONSES,\n"
    '    dependencies=[requires(declare("receipt_segment.read"))],\n',
    '    operation_id="getEvidenceLink",\n'
    '    summary="One confirmed evidence link, so a screen can resolve what a publication cites.",\n'
    "    responses=RESPONSES,\n",
)
assert s != before, "control 7 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "7. the evidence link read is reachable without a permission"

# 8. The bundle's segment list loses its guard. Separate from 7 because the two routes live in
#    different modules and the segment sweep is the test that has to notice this one.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/receipt_segments.py")
s = p.read_text()
before = s
s = s.replace(
    '    operation_id="listBundleReceiptSegments",\n'
    '    summary="Every segment cut from one bank result bundle, oldest first.",\n'
    "    responses=RESPONSES,\n"
    '    dependencies=[requires(declare("receipt_segment.read"))],\n',
    '    operation_id="listBundleReceiptSegments",\n'
    '    summary="Every segment cut from one bank result bundle, oldest first.",\n'
    "    responses=RESPONSES,\n",
)
assert s != before, "control 8 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "8. the bundle segment list is reachable without a permission"

echo
echo "=== restored ==="
git status --short
