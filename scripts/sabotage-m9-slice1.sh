#!/usr/bin/env bash
# Negative controls for M9 slice 1 — matching candidates.
#
# The slice's central claim is a negative: accepting a candidate decides nothing financial. A
# negative property is exactly where a control can be wrong rather than the gate, so each
# sabotage below breaks one specific thing and names the test that must catch it.
#
# **The first two are the pair that matters.** One makes acceptance write the attempt; the other
# grants the privilege that would let it. A suite that catches only the first is testing today's
# code rather than what the process is permitted to do.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

# **Every file this script touches is restored from a copy, never with `git checkout --`.**
# The first version reverted `registry.py` that way for control 8 and destroyed the slice's own
# uncommitted entries: `git checkout` restores from HEAD, and HEAD does not yet contain work in
# progress. Every other sabotage script in this repository uses the copy pattern; deviating from
# it for one control cost an hour of rewriting.
COMMANDS="services/backend/app/commands/matching_candidate.py"
MODEL="services/backend/app/db/models/matching_candidate.py"
ROUTES="services/backend/app/api/v1/matching_candidates.py"
MIGRATION="services/backend/alembic/versions/20260829_0028_matching_candidates.py"
REGISTRY="services/backend/app/audit/registry.py"
BACKUP="$(mktemp -d)"

cp "$COMMANDS" "$BACKUP/commands.py"
cp "$MODEL" "$BACKUP/model.py"
cp "$ROUTES" "$BACKUP/routes.py"
cp "$MIGRATION" "$BACKUP/migration.py"
cp "$REGISTRY" "$BACKUP/registry.py"

restore() {
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/model.py" "$MODEL"
  cp "$BACKUP/routes.py" "$ROUTES"
  cp "$BACKUP/migration.py" "$MIGRATION"
  cp "$BACKUP/registry.py" "$REGISTRY"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_matching_candidates.py
UNIT=tests/backend/test_candidate_schema.py
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

echo "== M9 slice 1 negative controls =="

# 1. The whole milestone in one line. Make acceptance mark the attempt paid — the shortcut three
#    documents exist to forbid, and the one a reviewer would reach for because at that moment they
#    have decided the receipt *is* the payment.
perl -0pi -e 's/(    permitted = PERMITTED_TRANSITIONS\.get\(candidate\.status, frozenset\(\)\))/    if target == CANDIDATE_ACCEPTED:\n        attempt = session.get(PaymentAttempt, candidate.payment_attempt_id)\n        if attempt is not None:\n            attempt.status = "paid"\n$1/' "$COMMANDS"
run "acceptance marks the attempt paid" "test_accepting_a_candidate_changes_nothing" "$LIVE"

# 2. The privilege behind it. Grant UPDATE on `payment_attempts` in slice 1's migration, which is
#    what would make sabotage 1 *succeed* rather than fail against PostgreSQL. This is the control
#    that proves the security test is doing something the behavioural test cannot.
perl -0pi -e 's/(        bind\.execute\(\n            sa\.text\(f.GRANT UPDATE \(\{columns\}\) ON public\."matching_candidates" TO "\{role\}".\)\n        \))/$1\n        bind.execute(sa.text(f\x27GRANT UPDATE ON public."payment_attempts" TO "{role}"\x27))/' "$MIGRATION"
run "the migration grants UPDATE on attempts" "test_the_runtime_holds_no_privilege_on_payment_attempts" "$LIVE"

# 3. Accept a reason-less rejection. `05_API_Specification.md:1820` requires one, and the
#    implementation requires it always because no threshold is approved.
perl -0pi -e 's/    if reason_required and not \(command\.reason or ""\)\.strip\(\):/    if False:/' "$COMMANDS"
run "a rejection needs no reason" "test_a_rejection_without_a_reason_is_refused" "$LIVE"

# 4. Make `accepted_for_confirmation` terminal again — the mistake the first draft of the model
#    made. It refuses the override document 05 describes, and being stricter than an approved
#    document is still deviation.
perl -0pi -e 's/    CANDIDATE_ACCEPTED: frozenset\(\r?\n        \{CANDIDATE_REJECTED, CANDIDATE_SUPERSEDED, CANDIDATE_EXPIRED\}\r?\n    \),/    CANDIDATE_ACCEPTED: frozenset(),/' "$MODEL"
run "acceptance is terminal again" "test_acceptance_is_not_terminal" "$UNIT"

# 5. Drop the transition check entirely, so a rejected candidate can be accepted afterwards. The
#    status catalogue marks `rejected` terminal; without this the table is a dictionary nothing
#    consults.
perl -0pi -e 's/    if target not in permitted:/    if False:/' "$COMMANDS"
run "terminal states accept transitions" "test_a_rejected_candidate_takes_no_further_decision" "$LIVE"

# 6. Let a proposal rewrite any segment's status, not only the two the state machine draws arrows
#    from. A suggestion would then overwrite a segment somebody had already decided.
perl -0pi -e 's/    if segment\.status in SEGMENT_GAINS_A_CANDIDATE_FROM:/    if True:/' "$COMMANDS"
run "a proposal rewrites a decided segment" "test_a_proposal_moves_the_segment_to_candidate_found" "$LIVE"

# 7. Guard the decisions with the *creation* permission. Both are candidate permissions, so a
#    negative test signing in as a role holding neither would pass — which is why the live tests
#    use `system_worker`, holding `create` and not `review`.
perl -0pi -e 's/(\@router\.post\(\n    "\/\{candidate_id\}\/accept-for-confirmation",(?:.|\n)*?)requires\(declare\("matching_candidate\.review"\)\)/$1requires(declare("matching_candidate.create"))/' "$ROUTES"
run "the decision takes the creation grant" "test_accepting_needs_the_review_permission" "$LIVE"

# 8. Write an audit action the catalogue does not name. `audit_outbox_catalog.yaml:39` names
#    exactly one candidate action and the acceptance test reads it by name.
perl -0pi -e 's/    audit_action="matching_candidate\.accepted_for_confirmation",/    audit_action="matching_candidate.accepted",/' "$REGISTRY"
run "the audit action is renamed" "test_" "tests/backend/test_name_registry_and_errors.py"

echo "== done =="
