#!/usr/bin/env bash
# Negative controls for G-5 — batch cancellation, split by state.
#
# The slice's claim is that authority now depends on the batch's status: `cancel_draft` before a
# manager has decided, `cancel_approved` after. That claim has two failure modes and they are
# opposites — a check that refuses too little (the accountant reaches an approved batch) and one
# that refuses too much (the manager cannot cancel anything). Each sabotage below breaks one of
# them, and a test suite that catches only one direction has not tested a split.
#
# Two more cover the governance half, where the failure is not a wrong answer but a claim nobody
# checks: a permission seeded and granted to nobody, or seeded in one copy of the catalogue.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/payment_batch.py"
ROUTES="services/backend/app/api/v1/payment_batches.py"
MIGRATION="services/backend/alembic/versions/20260828_0027_cancel_approved_permission.py"
INLINE="services/backend/app/security/permission_catalogue.py"
GUARDS="tests/backend/test_permission_guards.py"
BACKUP="$(mktemp -d)"

cp "$COMMANDS" "$BACKUP/commands.py"
cp "$ROUTES" "$BACKUP/routes.py"
cp "$MIGRATION" "$BACKUP/migration.py"
cp "$INLINE" "$BACKUP/inline.py"
cp "$GUARDS" "$BACKUP/guards.py"

restore() {
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/routes.py" "$ROUTES"
  cp "$BACKUP/migration.py" "$MIGRATION"
  cp "$BACKUP/inline.py" "$INLINE"
  cp "$BACKUP/guards.py" "$GUARDS"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_batch_cancellation.py
RBAC=tests/backend/test_rbac_seed_matches_catalogue.py
DOD=tests/backend/test_m6_definition_of_done.py
OUT="$BACKUP/out.txt"

run() {
  local label="$1" expect="$2" target="$3"
  "$PYTHON" -m pytest -c services/backend/pyproject.toml "$target" -q > "$OUT" 2>&1

  if ! grep -qE '[0-9]+ (passed|failed)' "$OUT"; then
    printf '  INVALID RUN  %s\n' "$label"
    tail -4 "$OUT"
    restore
    return
  fi
  if grep -qE '[0-9]+ failed' "$OUT"; then
    printf '  CAUGHT   %-52s' "$label"
    if grep -q "$expect" "$OUT"; then
      echo "(on: $expect)"
    else
      echo "*** WRONG ASSERTION *** expected: $expect"
      grep -E '^FAILED' "$OUT" | head -4
    fi
  else
    printf '  NOT CAUGHT  %s\n' "$label"
  fi
  restore
}

# For a sabotage that cannot reach a test at all. Removing a permission from the inlined catalogue
# makes `declare()` raise while the route module is being imported, so the suite never collects and
# there is no "N failed" line to read — `run` would call that an INVALID RUN and hide the strongest
# result in the file. A failure that happens before a request is served is a better catch than a
# red test, and it deserves to be reported as one rather than as a broken harness.
run_at_import() {
  local label="$1" expect="$2" target="$3"
  if "$PYTHON" -m pytest -c services/backend/pyproject.toml "$target" -q > "$OUT" 2>&1; then
    printf '  NOT CAUGHT  %s\n' "$label"
    restore
    return
  fi
  printf '  CAUGHT   %-52s' "$label"
  if grep -q "$expect" "$OUT"; then
    echo "(at import: $expect)"
  else
    echo "*** WRONG FAILURE *** expected: $expect"
    tail -4 "$OUT"
  fi
  restore
}

echo "== G-5 batch cancellation negative controls =="

# 1. Refuse too little. Let every cancellable status take the draft permission, which is the
#    implementation somebody writes when they read "make approved batches cancellable" and stop
#    there. The accountant then unmakes a manager's decision.
perl -0pi -e 's/    if status in CANCELLABLE_BY_MANAGER_ONLY:\r?\n        return CANCEL_APPROVED_OPERATION\r?\n//' "$COMMANDS"
run "an approved batch takes the draft grant" "test_an_accountant_cannot_cancel_an_approved_batch" "$LIVE"

# 2. Refuse too much, the opposite error and the one a single-direction test suite misses. Require
#    the manager grant for every origin: the split becomes a widening, and the accountant loses
#    the cancellation they have had since M6.
perl -0pi -e 's/CANCELLABLE_BATCH_STATUSES: tuple\[str, \.\.\.\] = \(BATCH_DRAFT, BATCH_READY\)/CANCELLABLE_BATCH_STATUSES: tuple[str, ...] = ()\nCANCELLABLE_EVERYTHING_SABOTAGE: tuple[str, ...] = (BATCH_DRAFT, BATCH_READY)/' "$COMMANDS"
perl -0pi -e 's/CANCELLABLE_BY_MANAGER_ONLY: tuple\[str, \.\.\.\] = \(BATCH_APPROVED,\)/CANCELLABLE_BY_MANAGER_ONLY: tuple[str, ...] = (BATCH_APPROVED, BATCH_DRAFT, BATCH_READY)/' "$COMMANDS"
run "every origin needs the manager grant" "test_a_ready_for_approval_batch_is_cancelled" "$LIVE"

# 3. Drop the authority check entirely and keep the route's guard. This is the shape the slice
#    exists to prevent: the route admits either grant, so with no state check *both* roles can
#    cancel *anything* — and the route still looks correctly guarded.
perl -0pi -e 's/    required = authority_for_cancelling\(batch\.status\)\r?\n    if required not in command\.held_permissions:\r?\n        raise ForbiddenError\(\)\r?\n/    required = authority_for_cancelling(batch.status)\n    del required\n/' "$COMMANDS"
run "the state check is removed" "test_an_accountant_cannot_cancel_an_approved_batch" "$LIVE"

# 4. Cancel an approved batch without saying the approval stopped authorising anything. The batch
#    row still says cancelled, so every status assertion passes; what disappears is the answer to
#    "why is the approval I remember no longer in force", keyed by the approval's own id.
perl -0pi -e 's/    if previous_status in CANCELLABLE_BY_MANAGER_ONLY:\r?\n        _audit_approval_invalidated_by_cancellation\(/    if False:\n        _audit_approval_invalidated_by_cancellation(/' "$COMMANDS"
run "the approval invalidation is not audited" "test_an_approved_batch_is_cancelled_by_the_manager" "$LIVE"

# 5. Record the previous status as a literal `draft`, which is what the audit row said before this
#    slice — correct while draft was the only cancellable status and a false statement about every
#    other one. The cancellation still happens; only the history lies.
perl -0pi -e 's/            previous_values=\{"status": previous_status\},/            previous_values={"status": BATCH_DRAFT},/' "$COMMANDS"
run "the audit row claims every cancellation was a draft" "test_cancelling_an_approved_batch_voids" "$LIVE"

# 6. Seed the permission and grant it to nobody — `20260816_0014`'s shape, which was right there
#    and is wrong here. Under deny-by-default the manager cannot cancel anything, so the owner's
#    decision exists in the catalogue and authorises no one.
perl -0pi -e 's/CANCELLATION_GRANTS: tuple\[tuple\[str, str\], \.\.\.\] = \(\r?\n    \("manager", "payment_batch\.cancel_approved"\),\r?\n\)/CANCELLATION_GRANTS: tuple[tuple[str, str], ...] = ()/' "$MIGRATION"
run "the permission is granted to nobody" "test_" "$RBAC"

# 7. Add the permission to the migration and not to the runtime's inlined copy. `docs/` is not in
#    the container image, so these two lists are the same fact stored twice — and the failure is a
#    permission that exists in the database and is unknown to the process that checks it.
#
#    Caught **at import**, not by a test: `declare("payment_batch.cancel_approved")` runs while the
#    route module loads and `UnknownPermission` stops the process. So the drift cannot reach a
#    deployment at all, which is the behaviour `app/security/permissions.py` was written for and a
#    stronger outcome than a red assertion.
perl -0pi -e 's/        "payment_batch\.cancel_approved",\r?\n//' "$INLINE"
run_at_import "the inlined catalogue misses the permission" "UnknownPermission" "$RBAC"

# 8. The reader, not the rule. Make `guards_admitting_only` ask "does the route name one" again —
#    the reading G-5 replaced. The cancel route names `cancel_approved` as an *alternative*, so
#    this fails the M6 prohibition on a route that keeps its property perfectly, which is why the
#    distinction had to be made in the reader rather than by exempting the route.
perl -0pi -e 's/        group for group in permission_alternatives\(route\) if group and group <= restricted/        group for group in permission_alternatives(route) if group \& restricted/' "$GUARDS"
run "the reader confuses naming with requiring" "test_no_batch_route_requires_a_manager_only" "$DOD"

echo "== done =="
