#!/usr/bin/env bash
# Negative controls for M0 slice C — the evidence link list, and the confirmation that can finally
# cite a document instead of an excuse.
#
# **Two kinds of control per read, deliberately.** Three times this milestone a control found a new
# read tested only for who may call it: blanking the field a screen depends on changed nothing any
# assertion could see. So controls 1 and 2 attack the guard, and 3 and 4 attack the content.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@172.17.0.2:5432/postgres}"

ROUTE=services/backend/app/api/v1/evidence_links.py

BACKUP=$(mktemp -d)
cp "$ROUTE" "$BACKUP/evidence_links.py"
restore() { cp "$BACKUP/evidence_links.py" "$ROUTE"; }
trap restore EXIT

SUITE="tests/backend tests/integration/test_evidence_links.py"

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
    grep '^FAILED' "$BACKUP/out.txt" | head -4
  fi
  restore
}

# 1. The list loses its guard, so anybody with a session can read which segment proves which
#    payment — across every attempt in the centre, one id at a time.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/evidence_links.py")
s = p.read_text()
before = s
s = s.replace(
    '    operation_id="listEvidenceLinks",\n'
    '    summary="Every evidence link for one payment attempt, oldest first.",\n'
    "    responses=RESPONSES,\n"
    '    dependencies=[requires(declare("receipt_segment.read"))],\n',
    '    operation_id="listEvidenceLinks",\n'
    '    summary="Every evidence link for one payment attempt, oldest first.",\n'
    "    responses=RESPONSES,\n",
)
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "1. the evidence link list is reachable without a permission"

# 2. The scoping parameter becomes optional and defaults to "everything". **The disclosure this
#    route was shaped to avoid**: a caller who omits it gets every evidence link in the centre,
#    and every status code stays exactly what it was.
#
#    **The parameter moves to the end rather than gaining a default in place.** The first version
#    of this control left `payment_attempt_id: uuid.UUID | None = None` ahead of two parameters
#    with no defaults, which is a `SyntaxError` — the module stopped importing and `conftest.py`
#    failed to load. It reported CAUGHT with zero failing tests, which is the tell: a control that
#    crashes the suite proves the sabotage is *detectable*, not that anything is *checking* the
#    property. A sabotage has to produce a working system that is wrong.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/evidence_links.py")
s = p.read_text()
before = s
s = s.replace(
    "def list_evidence_links(\n"
    "    payment_attempt_id: uuid.UUID,\n"
    "    actor: Annotated[ActorContext, Depends(authenticated_actor)],\n"
    "    runtime: Annotated[RuntimeServices, Depends(get_runtime)],\n",
    "def list_evidence_links(\n"
    "    actor: Annotated[ActorContext, Depends(authenticated_actor)],\n"
    "    runtime: Annotated[RuntimeServices, Depends(get_runtime)],\n"
    "    payment_attempt_id: uuid.UUID | None = None,\n",
)
s = s.replace(
    "                select(ConfirmedEvidenceLink)\n"
    "                .where(ConfirmedEvidenceLink.payment_attempt_id == payment_attempt_id)\n",
    "                select(ConfirmedEvidenceLink)\n",
)
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "2. the list is unscoped and returns every link in the centre"

# 3. Replaced links are filtered out, so a corrected attempt reads as one that was always right.
#    Nothing about the active link changes, which is what makes this the subtle one.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/evidence_links.py")
s = p.read_text()
before = s
s = s.replace(
    "                .where(ConfirmedEvidenceLink.payment_attempt_id == payment_attempt_id)\n",
    "                .where(\n"
    "                    ConfirmedEvidenceLink.payment_attempt_id == payment_attempt_id,\n"
    "                    ConfirmedEvidenceLink.status == LINK_ACTIVE,\n"
    "                )\n",
)
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "3. the list hides that the evidence was ever corrected"

# 4. The order reverses, so a replacement is listed before what it replaced. Every row is present
#    and every status is right; only the story is backwards.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/evidence_links.py")
s = p.read_text()
before = s
s = s.replace(
    ".order_by(ConfirmedEvidenceLink.confirmed_at, ConfirmedEvidenceLink.id)",
    ".order_by(ConfirmedEvidenceLink.confirmed_at.desc(), ConfirmedEvidenceLink.id.desc())",
)
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "4. the replacement is listed before what it replaced"

echo
echo "=== restored ==="
git status --short "$ROUTE"
