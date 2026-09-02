#!/usr/bin/env bash
# Negative controls for M10 slice 3 — the statement file and its versioned import runs.
#
# Controls 1 and 2 attack the sentence the slice exists for: doc 08 §8.2, "Reprocessing never
# overwrites earlier rows. It creates a new import run." Both are *helpful* changes — reuse the
# run rather than making a new one, keep the number the same — and both are what somebody does
# when a reparse looks like a retry.
#
# Control 10 is the one no behavioural test can make: widening a grant. A run whose
# `parser_version` the runtime may rewrite is a run that cannot be told apart from a different
# parse, and only a privilege query sees that.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/bank_statement.py"
ROUTES="services/backend/app/api/v1/bank_statements.py"
MIGRATION="services/backend/alembic/versions/20260906_0037_bank_statement_import.py"
BACKUP="$(mktemp -d)"

cp "$COMMANDS" "$BACKUP/commands.py"
cp "$ROUTES" "$BACKUP/routes.py"
cp "$MIGRATION" "$BACKUP/migration.py"

restore() {
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/routes.py" "$ROUTES"
  cp "$BACKUP/migration.py" "$MIGRATION"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_bank_statement_import.py
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

echo "== M10 slice 3 negative controls =="

# 1. Every run is number 1. The unique then refuses the second parse outright, which looks like a
#    working guard and is in fact the loss of the whole history.
perl -0pi -e 's/        run_number=_next_run_number\(session, statement\),/        run_number=1,/' "$COMMANDS"
run "every parse is run number one" "test_the_first_run_is_number_one" "$LIVE"

# 2. Count the runs instead of reading the highest number.
#
#    **This went NOT CAUGHT on the first run, and it was the third meaning: the sabotage did not
#    break the property the suite could reach.** While no run is ever deleted, `count` and `max`
#    return the same number, and every existing test worked from a history with no holes in it.
#
#    Document 08 §24 puts "import runs and rows" among the objects retention covers, so a purged
#    run is a state production reaches — and after one, counting hands out a number that already
#    exists. `test_a_deleted_run_does_not_free_its_number` was written for that state, and the
#    control is kept rather than deleted because it is now the thing that guards the new test.
perl -0pi -e 's/    highest = session\.scalar\(\r?\n        select\(func\.max\(BankStatementImportRun\.run_number\)\)\.where\(/    highest = session.scalar(\n        select(func.count(BankStatementImportRun.run_number)).where(/' "$COMMANDS"
run "run numbers are counted, not read" "test_a_deleted_run_does_not_free_its_number" "$LIVE"

# 3. Number runs globally rather than per file. A second statement's first parse becomes "run 2",
#    and an operator looks for a predecessor that never existed.
perl -0pi -e 's/        select\(func\.max\(BankStatementImportRun\.run_number\)\)\.where\(\r?\n            BankStatementImportRun\.bank_statement_file_id == statement\.id\r?\n        \)/        select(func.max(BankStatementImportRun.run_number))/' "$COMMANDS"
run "run numbers are global, not per file" "test_run_numbers_are_per_file_not_global" "$LIVE"

# 4. Let a draft mapping parse. §8.1 says approved mappings, and a draft has not been reviewed.
perl -0pi -e 's/    if mapping\.status != APPROVED_MAPPING_STATUS:/    if False:/' "$COMMANDS"
run "an unapproved mapping parses a statement" "test_a_draft_mapping_cannot_parse" "$LIVE"

# 5. Let an export mapping parse a statement. It reads different columns; the failure would look
#    like a bad statement rather than a misconfiguration.
perl -0pi -e 's/    if mapping\.file_type != STATEMENT_MAPPING_TYPE:/    if False:/' "$COMMANDS"
run "an export mapping parses a statement" "test_an_export_mapping_cannot_parse" "$LIVE"

# 6. Let a mapping from another bank version parse. §8.2 asks for the exact version, and this is
#    the half of BANK-VER-005's question that a schema can answer.
perl -0pi -e 's/    if mapping\.bank_profile_version_id != statement\.bank_profile_version_id:/    if False:/' "$COMMANDS"
run "another bank version's mapping parses" "test_a_mapping_from_another_bank_version" "$LIVE"

# 7. Accept an outgoing-only account as a statement destination. The bank's record of receipts
#    would then sit against the ledger the platform reads when it pays people.
perl -0pi -e 's/    if account\.account_role not in INCOMING_ACCOUNT_ROLES:/    if False:/' "$COMMANDS"
run "an outgoing account receives a statement" "test_an_outgoing_account_cannot_receive" "$LIVE"

# 8. Accept a file the scanner has not cleared. The parse opens it, on a worker.
perl -0pi -e 's/    if record\.scan_status != CLEAN_SCAN_STATUS:/    if False:/' "$COMMANDS"
run "an unscanned file is imported" "test_an_unscanned_file_cannot_be_imported" "$LIVE"

# 9. Open the surface to a trader. Every route, because the control that removes one guard while
#    four remain proves only that four remain.
perl -0pi -e 's/dependencies=\[requires\(declare\("bank_statement\.(upload|import|read)"\)\)\],\r?\n//g' "$ROUTES"
run "a trader reaches the statement surface" "test_no_trader_can_see_or_touch_a_statement" "$LIVE"

# 10. Widen the grant so the runtime may rewrite which parser produced a run. Nothing behavioural
#     can see this: the command still writes the right value, and the *capability* to change it
#     afterwards is what the control adds. Only `information_schema.column_privileges` answers.
perl -0pi -e 's/RUN_GRANTED_COLUMNS = \(\r?\n    "status",/RUN_GRANTED_COLUMNS = (\n    "parser_version",\n    "status",/' "$MIGRATION"
run "a run's parser becomes rewritable" "test_the_runtime_cannot_rewrite_a_runs_provenance" "$LIVE"

# 11. Let the statement file's bank version be rewritten after upload. §10.4 calls the file the
#     immutable original, and a version that can change afterwards makes every run against it
#     unexplainable.
perl -0pi -e 's/FILE_GRANTED_COLUMNS = \(\r?\n    "status",/FILE_GRANTED_COLUMNS = (\n    "bank_profile_version_id",\n    "status",/' "$MIGRATION"
run "a statement's bank version becomes mutable" "test_the_runtime_cannot_rewrite_a_runs_provenance" "$LIVE"

# 12. Record a hash of the platform's own invention rather than the file's. It satisfies a
#     not-null check and proves nothing about which bytes were read — the shape of a gate whose
#     input is incomplete, applied to provenance.
perl -0pi -e 's/    return record\.sha256_hash/    return "0" * 64/' "$COMMANDS"
run "the source hash is invented" "test_the_run_records_which_parser_read" "$LIVE"

# 13. Mark the statement parsed on upload. Document 06 §10.3 moves it there only when a run
#     succeeds, and nothing has read the file yet.
perl -0pi -e 's/        status=FILE_UPLOADED,/        status="parsed",/' "$COMMANDS"
run "an upload claims to have been parsed" "test_an_upload_is_uploaded_and_nothing_more" "$LIVE"

# 14. Enqueue nothing. The run sits `queued` forever and no parser ever reads it — a row that
#     describes work nobody will do.
perl -0pi -e 's/    run\.created_by_job_id = job\.id/    run.created_by_job_id = None/' "$COMMANDS"
run "no job is enqueued for the run" "test_the_run_records_which_parser_read" "$LIVE"

echo "== done =="
