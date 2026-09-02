#!/usr/bin/env bash
# Negative controls for M10 slice 5 — a candidate, never a truth.
#
# Controls 1 to 4 attack the one sentence the slice exists for: doc 05 §21.5, "Candidate acceptance
# and financial confirmation remain separate." Each is a *helpful* change — fill the confirmation
# from the claim, mark the receipt confirmed, propose as already accepted, let the body carry a
# confirmed amount — and each is the mistake somebody makes when a suggestion and a decision look
# like one act.
#
# Control 9 is the one no behavioural test can make: a partial unique index answers §10.7 `:809`'s
# cardinality question in a migration, and every test above it still passes.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/incoming_match.py"
ROUTES="services/backend/app/api/v1/incoming_matches.py"
MIGRATION="services/backend/alembic/versions/20260909_0040_incoming_payment_matches.py"
MODEL="services/backend/app/db/models/incoming_match.py"
BACKUP="$(mktemp -d)"

cp "$COMMANDS" "$BACKUP/commands.py"
cp "$ROUTES" "$BACKUP/routes.py"
cp "$MIGRATION" "$BACKUP/migration.py"
cp "$MODEL" "$BACKUP/model.py"

restore() {
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/routes.py" "$ROUTES"
  cp "$BACKUP/migration.py" "$MIGRATION"
  cp "$BACKUP/model.py" "$MODEL"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_incoming_payment_matches.py
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
    printf '  CAUGHT   %-56s' "$label"
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

echo "== M10 slice 5 negative controls =="

# 1. Fill the confirmation from the receipt's claim. The most tempting change in the slice: the
#    trader said how much and the row says how much, so why ask again? Because nobody has looked at
#    the two side by side, which is what slice 6 is.
perl -0pi -e 's/        match_reasons=list\(command\.match_reasons\),\r?\n        record_version=1,/        match_reasons=list(command.match_reasons),\n        confirmed_amount_irr=receipt.amount_irr,\n        record_version=1,/' "$COMMANDS"
run "the proposal confirms its own amount" "test_a_match_confirms_nothing" "$LIVE"

# 2. Move the receipt to a confirmed state. §10.3 puts four statuses between candidate_match and
#    incoming_payment_confirmed, and this jumps them.
perl -0pi -e 's/    receipt\.status = RECEIPT_CANDIDATE_MATCH/    receipt.status = "confirmed"/' "$COMMANDS"
run "the receipt jumps to confirmed" "test_a_match_confirms_nothing" "$LIVE"

# 3. Propose as already accepted. Document 06 §11.3's first rule: "Candidate acceptance is not
#    financial confirmation" — but it is still a person agreeing, and nobody has.
perl -0pi -e 's/        status=MATCH_PROPOSED,/        status="accepted_for_review",/' "$COMMANDS"
run "a proposal is born accepted" "test_a_match_confirms_nothing" "$LIVE"

# 4. Let the request body carry a confirmed amount. A field the command would then have to refuse
#    is a field that should not exist.
perl -0pi -e 's/    model_config = ConfigDict\(extra="forbid"\)\r?\n\r?\n    bank_statement_row_id: uuid\.UUID/    model_config = ConfigDict(extra="allow")\n\n    bank_statement_row_id: uuid.UUID/' "$ROUTES"
run "the body accepts a confirmation" "test_the_body_cannot_carry_a_confirmation" "$LIVE"

# 5. Match against a row from a run that has not finished. Document 08 §8.2 makes rows available
#    for matching after the import settles, and a row from a running parse belongs to work nobody
#    has completed.
perl -0pi -e 's/    if run\.status != RUN_SUCCEEDED:/    if False:/' "$COMMANDS"
run "an unfinished parse's row is matchable" "test_a_row_from_an_unfinished_run" "$LIVE"

# 6. Read-then-insert instead of letting the unique decide. Both racers pass the SELECT; the
#    integrity error then escapes as a 500 rather than a conflict an accountant can act on.
perl -0pi -e 's/    except IntegrityError as error:/    except ValueError as error:/' "$COMMANDS"
run "the unique race surfaces as a 500" "test_two_accountants_proposing_the_same_pair" "$LIVE"

# 7. Reject without recording who. §8.8 requires actor, time and reason; the table's CHECK requires
#    the pair, so this fails at the database — which is the point of having the CHECK.
perl -0pi -e 's/    match\.rejected_by_admin_user_id = actor\.actor_id/    match.rejected_by_admin_user_id = None/' "$COMMANDS"
run "a rejection records no actor" "test_a_rejection_records_who_and_why" "$LIVE"

# 8. Accept a blank rejection reason. §8.8 requires a reason, and a blank one records two of the
#    three things a decision must carry.
#
#    **This went NOT CAUGHT on the first run, and it was the second meaning: the gate was
#    missing.** Every rejection test sent a real sentence, so nothing ever asked what happens
#    without one — the sabotage was fine and there was no assertion for it to break.
#    `test_a_rejection_without_a_reason_is_refused` was written for it, and covers whitespace as
#    well as empty because `min_length` does not.
perl -0pi -e 's/    if not command\.rejection_reason\.strip\(\):/    if False:/' "$COMMANDS"
perl -0pi -e 's/    rejection_reason: str = Field\(min_length=1, max_length=2000\)/    rejection_reason: str = Field(max_length=2000)/' "$ROUTES"
run "a rejection needs no reason" "test_a_rejection_without_a_reason_is_refused" "$LIVE"

# 9. Add the partial unique §10.7 `:809` leaves to the business — "one active match per row". Every
#    behavioural test still passes, because none of them proposes a second match for a row that
#    already has one in a non-terminal state. Only a look at the indexes sees it.
perl -0pi -e 's/    bind = op\.get_bind\(\)/    op.create_index(\n        "uq_incoming_matches_one_active_row",\n        "incoming_payment_matches",\n        ["bank_statement_row_id"],\n        unique=True,\n        postgresql_where=sa.text("status = \x27proposed\x27"),\n    )\n    bind = op.get_bind()/' "$MIGRATION"
run "a partial unique decides the cardinality" "test_no_partial_unique_constrains_the_pair" "$LIVE"

# 10. Widen the grant so the runtime may rewrite which row a candidate names. Nothing behavioural
#     changes — no command updates it — and a candidate whose evidence can be swapped afterwards is
#     one nobody can audit.
perl -0pi -e 's/GRANTED_COLUMNS = \(\r?\n    "status",/GRANTED_COLUMNS = (\n    "bank_statement_row_id",\n    "status",/' "$MIGRATION"
run "a candidate's row becomes rewritable" "test_the_runtime_cannot_rewrite_a_candidates_evidence" "$LIVE"

# 11. Give a human search a score of 1.0. It makes a person's judgement indistinguishable from a
#     machine's certainty, which is the argument the outgoing direction records on the same column.
perl -0pi -e 's/        match_score=command\.match_score,/        match_score=command.match_score if command.match_score is not None else 1,/' "$COMMANDS"
run "a human search is given full confidence" "test_the_method_is_recorded_as_a_human_search" "$LIVE"

# 12. Open the surface to a trader. Which bank row proves a claim is the centre's judgement, and a
#     trader who could propose one would be deciding their own case.
perl -0pi -e 's/    dependencies=\[requires\(declare\("incoming_payment\.match"\)\)\],\r?\n//g' "$ROUTES"
perl -0pi -e 's/    dependencies=\[requires\(declare\("incoming_receipt\.read"\)\)\],\r?\n//g' "$ROUTES"
run "a trader reaches the matching surface" "test_no_trader_can_reach_the_matching_surface" "$LIVE"

# 13. Answer 400 rather than 404 for a match under another receipt. The path asserts a
#     relationship, and "wrong receipt" confirms the match exists.
perl -0pi -e 's/            raise NotFoundError\(\)\r?\n\r?\n        result = match_commands\.reject_match\(/            raise BusinessRuleViolationError("wrong receipt")\n\n        result = match_commands.reject_match(/' "$ROUTES"
perl -0pi -e 's/from app\.core\.errors import \(\r?\n    ErrorEnvelope,/from app.core.errors import (\n    BusinessRuleViolationError,\n    ErrorEnvelope,/' "$ROUTES"
run "a foreign match answers 400 not 404" "test_a_match_under_another_receipt_is_not_found" "$LIVE"

echo "== done =="
