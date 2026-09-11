#!/usr/bin/env bash
# Negative controls for M0 slice A — the correction split and the activation grant.
#
# This slice is three `role_permissions` rows. There is no algorithm to break, so every control
# below attacks a *claim* instead: that the grant reached the role it names, that the split still
# refuses one human once the grants make the command reachable, that the route asks for the
# preparer's half and not the approver's, and that the catalogue and the seed cannot drift apart.
#
# Controls 6 and 7 are the ones this slice was written for. The interim rule — "nobody holds
# either half" — was true for two milestones and made three separate tests pass for a reason that
# had nothing to do with what they claimed to check. Those two make the *new* rule fail loudly if
# it is quietly reverted, which the old shape could not do.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

MIGRATION=services/backend/alembic/versions/20260914_0045_correction_split_grants.py
ROUTE=services/backend/app/api/v1/payment_publications.py
COMMAND=services/backend/app/commands/publication_correction.py
CATALOG=docs/governance/permission_catalog.yaml

BACKUP=$(mktemp -d)
cp "$MIGRATION" "$BACKUP/migration.py"
cp "$ROUTE" "$BACKUP/route.py"
cp "$COMMAND" "$BACKUP/command.py"
cp "$CATALOG" "$BACKUP/catalog.yaml"

restore() {
  cp "$BACKUP/migration.py" "$MIGRATION"
  cp "$BACKUP/route.py" "$ROUTE"
  cp "$BACKUP/command.py" "$COMMAND"
  cp "$BACKUP/catalog.yaml" "$CATALOG"
}
trap restore EXIT

SUITE="tests/integration/test_publication_correction.py \
tests/integration/test_bank_version_resolution.py \
tests/backend/test_rbac_seed_matches_catalogue.py \
tests/backend/test_m3_definition_of_done.py \
tests/backend/test_m5_definition_of_done.py \
tests/backend/test_governance_counts_reconcile.py"

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
$PY -m pytest $SUITE -q --no-header 2>&1 | tail -3

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if $PY -m pytest $SUITE -q --no-header >"$BACKUP/out.txt" 2>&1; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT: $(grep -c '^FAILED' "$BACKUP/out.txt") failing"
    grep '^FAILED' "$BACKUP/out.txt" | head -5
  fi
  restore
}

# 1. The preparer's grant never lands. The row the accountant needs is simply absent from the
#    migration — the shape a hurried revert takes, and the shape the world was in until this slice.
#    Nothing in the command changes, so every dual-control assertion still passes; what fails is
#    the one test that signs in as somebody a deployment actually has.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/alembic/versions/20260914_0045_correction_split_grants.py")
s = p.read_text()
before = s
s = s.replace('    ("accountant", "payment_attempt.correct_result"),\n', "")
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "1. the accountant never receives the preparer half"

# 2. The approver's grant never lands. Sharper than 1 in one way: the *caller* still gets through
#    the door, so the route guard is satisfied and the refusal has to come from the approver's own
#    roles being read — which is the half of the split that lives in the command.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/alembic/versions/20260914_0045_correction_split_grants.py")
s = p.read_text()
before = s
s = s.replace('    ("manager", "payment_publication.correct"),\n', "")
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "2. the manager never receives the approver half"

# 3. The activation grant never lands, which is the state `20260816_0014` deliberately left and
#    which made a bank that changed its rules unrecordable.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/alembic/versions/20260914_0045_correction_split_grants.py")
s = p.read_text()
before = s
s = s.replace('    ("business_admin", "bank_profile.activate_version"),\n', "")
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "3. the business_admin never receives the activation grant"

# 4. The grant goes to the wrong role — the accountant, which is the exact choice the owner
#    rejected and the reason the decision needed making. A control that only removed the row would
#    never see this: the permission is granted, to somebody, and every "is it granted at all"
#    assertion is satisfied.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/alembic/versions/20260914_0045_correction_split_grants.py")
s = p.read_text()
before = s
s = s.replace(
    '    ("business_admin", "bank_profile.activate_version"),',
    '    ("accountant", "bank_profile.activate_version"),',
)
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "4. the accountant activates bank versions instead of the business_admin"

# 5. `_refuse_a_single_human` stops refusing. **The control POL-002 names**, and until this slice
#    it was cheap to satisfy: nobody could reach the command, so nothing depended on the
#    comparison. Now the accountant can reach it, and one person holding both halves is a
#    configuration an administrator can produce.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/commands/publication_correction.py")
s = p.read_text()
before = s
s = s.replace(
    "    if command.prepared_by_admin_user_id == command.approved_by_admin_user_id:",
    "    if False:",
)
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "5. one person completes a correction alone"

# 6. **The split, inverted.** The route asks for `payment_publication.correct` — the approver's
#    grant — so the manager presses the button and names the accountant as the second human. Every
#    behavioural assertion about the correction still holds: two ids differ, the named approver
#    holds a grant, publication N+1 exists. The only thing that changed is which of the two humans
#    is doing the asking, and before the grants existed nothing could tell the difference.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/payment_publications.py")
s = p.read_text()
before = s
s = s.replace(
    '    dependencies=[requires(declare("payment_attempt.correct_result"))],\n'
    ")\ndef correct_payment_result_publication(",
    '    dependencies=[requires(declare("payment_publication.correct"))],\n'
    ")\ndef correct_payment_result_publication(",
)
assert s != before, "control 6 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "6. the route asks for the approver's grant, so the split runs backwards"

# 7. The catalogue keeps the old empty defaults while the migration grants. A reader consulting the
#    governance document is told nobody may correct anything, and the running system disagrees —
#    which is the failure mode `test_rbac_seed_matches_catalogue.py` exists for.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("docs/governance/permission_catalog.yaml")
s = p.read_text()
before = s
s = s.replace(
    "        default_roles: [accountant]\n"
    "        assignment: preparer_half_of_the_split_owner_decided_2026_09_08",
    "        default_roles: []\n"
    "        assignment: preparer_half_of_the_split_owner_decided_2026_09_08",
)
assert s != before, "control 7 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "7. the catalogue still says nobody may prepare a correction"

# 8. The catalogue is edited without re-hashing the M0 manifest. Not a behaviour change at all —
#    which is the point: the governance documents are gated by a digest precisely because an edit
#    that changes no test is the kind that gets made.
#
#    **This came back NOT CAUGHT the first time it was run, and that was the finding.**
#    `infra/scripts/m0_manifest.py` had exactly one caller in the repository —
#    `.github/workflows/m1-verify.yml:112` — and neither verifier script ran it, so the checksum
#    chain behind every M0 citation was checked only by a hosted runner. It is now also checked by
#    `test_every_governed_document_matches_its_recorded_digest`, which imports the script rather
#    than restating its convention. That test is what catches this control.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("docs/governance/permission_catalog.yaml")
s = p.read_text()
before = s
s = s.replace(
    "        default_roles: [business_admin]\n",
    "        default_roles: [business_admin]  # revisit after the trial\n",
)
assert s != before, "control 8 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "8. a governance edit lands without re-hashing the manifest"

echo
echo "=== restored ==="
git status --short
