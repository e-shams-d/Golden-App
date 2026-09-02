#!/usr/bin/env bash
# Negative controls for M10 slice 4B — duplicate detection.
#
# Control 1 is the whole section in one line: §8.7's "A warning does not automatically delete or
# merge data." Deduplicating on the way in satisfies every assertion anybody would think to write
# about the *first* row while destroying the evidence an accountant needs.
#
# Control 4 is the subtle one and the reason this module has the shape it has: removing the
# same-file exclusion makes every reparse flag itself completely, which is the specified workflow
# reporting itself as an error.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

DUPES="services/backend/app/statements/duplicates.py"
COMMANDS="services/backend/app/commands/statement_rows.py"
MIGRATION="services/backend/alembic/versions/20260908_0039_statement_duplicate_review.py"
BACKUP="$(mktemp -d)"

cp "$DUPES" "$BACKUP/duplicates.py"
cp "$COMMANDS" "$BACKUP/commands.py"
cp "$MIGRATION" "$BACKUP/migration.py"

restore() {
  cp "$BACKUP/duplicates.py" "$DUPES"
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/migration.py" "$MIGRATION"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_statement_duplicates.py
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

echo "== M10 slice 4B negative controls =="

# 1. Drop the duplicate instead of flagging it. The most tempting change in the slice — the row is
#    a duplicate, so why keep it? Because §8.7 says a warning never deletes data, and because the
#    repeat is the evidence that tells an accountant whether the bank sent it twice or the operator
#    uploaded it twice.
perl -0pi -e 's/    for parsed in result\.rows:\r?\n        session\.add\(_row_of\(run, parsed, flagged=parsed\.row_number in flagged\)\)/    for parsed in result.rows:\n        if parsed.row_number in flagged:\n            continue\n        session.add(_row_of(run, parsed, flagged=False))/' "$COMMANDS"
run "a duplicate row is dropped instead of flagged" "test_a_repeated_line_is_flagged_and_kept" "$LIVE"

# 2. Flag the first occurrence too. Doubles every count and leaves an accountant with no way to
#    see which line is the original.
perl -0pi -e 's/        else:\r?\n            seen_fingerprints\[row\.row_fingerprint\] = row\.row_number/        else:\n            seen_fingerprints[row.row_fingerprint] = row.row_number\n            findings.append(DuplicateFinding(row_number=row.row_number, signal="same_normalized_fingerprint"))/' "$DUPES"
run "the first occurrence is flagged as well" "test_a_repeated_line_is_flagged_and_kept" "$LIVE"

# 3. Open one task per duplicate row. A statement whose last week overlaps the previous upload
#    produces forty findings and one question; forty queue items bury it.
perl -0pi -e 's/    signals = sorted\(\{finding\.signal for finding in duplicates\.findings\}\)/    for _each in duplicates.findings:\n        open_task(OpenTask(task_type=TASK_TYPE_STATEMENT_DUPLICATE, entity_type=ENTITY_STATEMENT_IMPORT_RUN, entity_id=run.id, title="duplicate row", description="one per row", priority=5), session=session, policy=policy, actor=actor, context=context, now=now)\n    signals = sorted({finding.signal for finding in duplicates.findings})/' "$COMMANDS"
run "one task per duplicate row" "test_the_duplicate_opens_one_task_for_the_run" "$LIVE"

# 4. Compare against every earlier row, including other runs of the same file. **Every reparse
#    then flags itself completely** — the workflow document 08 §8.2 specifies, reporting itself as
#    a problem, which teaches an accountant to ignore the warning.
perl -0pi -e 's/        \.where\(BankStatementImportRun\.bank_statement_file_id != statement\.id\)\r?\n//' "$DUPES"
run "a reparse counts as a duplicate of itself" "test_a_reparse_is_not_a_duplicate_of_itself" "$LIVE"

# 5. Only look inside the current parse. The overlapping-period case — August, then a
#    July-to-August export — is the one that actually happens, and it is invisible from inside one
#    file.
perl -0pi -e 's/    findings\.extend\(_against_other_statements\(session, statement=statement, rows=rows\)\)/    pass/' "$DUPES"
run "cross-statement duplicates are not looked for" "test_the_same_transfer_in_a_second_statement" "$LIVE"

# 6. Drop the tracking-number signal. It catches what the fingerprint cannot: a bank re-sending one
#    transfer with a corrected date or amount, where the rows differ and the reference is the only
#    thing that says they are the same event.
perl -0pi -e 's/        reference = row\.tracking_number or row\.document_number/        reference = None/' "$DUPES"
run "the tracking-number signal is removed" "test_a_shared_tracking_number_is_its_own_signal" "$LIVE"

# 7. Skip the file-checksum signal. §26.2 names "duplicate file checksum" as a case this import
#    must handle, and it is the only one that catches a re-upload whose rows have all been
#    superseded.
perl -0pi -e 's/        duplicate_of_statement_file_id=_a_file_with_the_same_bytes\(session, statement\),/        duplicate_of_statement_file_id=None,/' "$DUPES"
run "an identical re-upload is not noticed" "test_the_same_file_uploaded_twice_opens_its_own_task" "$LIVE"

# 8. Name the most recent copy rather than the original. The question an operator is answering is
#    "is this the same file you already uploaded?", and the useful answer names the first one.
#
#    **This went NOT CAUGHT on the first run, and it was the third meaning.** The test uploaded the
#    same file twice, and with two copies `ASC` and `DESC` return the same single row — the
#    sabotage did not break the property the fixture could reach. A third upload distinguishes
#    them, and an operator retrying an upload twice is ordinary rather than contrived.
perl -0pi -e 's/        \.order_by\(BankStatementFile\.created_at\.asc\(\)\)/        .order_by(BankStatementFile.created_at.desc())/' "$DUPES"
run "the earlier statement is the one flagged" "test_the_same_file_uploaded_twice_opens_its_own_task" "$LIVE"

# 9. Let a duplicate signal overwrite `invalid`. The fact that nobody can read the row then
#    disappears from the preview, which is the hiding §22.2 refuses.
perl -0pi -e 's/            if flagged and parsed\.status != ROW_INVALID/            if flagged/' "$COMMANDS"
run "a duplicate signal hides an unreadable row" "test_an_unreadable_row_stays_invalid" "$LIVE"

# 10. Flag everything. The control that proves the rest of the module is evidence rather than a
#     detector nobody constrained — a test suite about duplicates passes entirely against this.
perl -0pi -e 's/    def flagged_rows\(self\) -> frozenset\[int\]:\r?\n        return frozenset\(finding\.row_number for finding in self\.findings\)/    def flagged_rows(self) -> frozenset[int]:\n        return frozenset(range(1, 200))/' "$DUPES"
run "every row is flagged as a duplicate" "test_a_clean_statement_opens_nothing" "$LIVE"

# 11. Reuse the outgoing-payment discrepancy type instead of declaring one. Files an
#     incoming-statement question in the queue an accountant filters for payment results, which is
#     the one thing `TASK_TYPES` exists to prevent.
perl -0pi -e 's/    "statement_duplicate_review",\r?\n\)/)/' "$MIGRATION"
run "the declared task type is removed from the CHECK" "test_the_duplicate_opens_one_task_for_the_run" "$LIVE"

echo "== done =="
