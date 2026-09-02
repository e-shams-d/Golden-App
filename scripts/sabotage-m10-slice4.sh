#!/usr/bin/env bash
# Negative controls for M10 slice 4 — the parsed rows.
#
# Controls 1 to 4 attack document 08 §8.5, whose rules are the ones a parser breaks by being
# helpful: fold the raw value too, convert the Jalali date, round the fractional amount, read a
# debit as a credit. Each is what somebody does when the normalized reading looks obviously
# better than the messy one the bank sent.
#
# Control 9 is the one no behavioural test can make. Granting UPDATE on a row changes nothing
# observable — the command never updates one — so only a privilege query sees it.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PARSER="services/backend/app/statements/parser.py"
COMMANDS="services/backend/app/commands/statement_rows.py"
MIGRATION="services/backend/alembic/versions/20260907_0038_bank_statement_rows.py"
MODEL="services/backend/app/db/models/bank_statement.py"
WORKER="services/backend/app/workers/tasks/files.py"
BACKUP="$(mktemp -d)"

cp "$PARSER" "$BACKUP/parser.py"
cp "$COMMANDS" "$BACKUP/commands.py"
cp "$MIGRATION" "$BACKUP/migration.py"
cp "$MODEL" "$BACKUP/model.py"
cp "$WORKER" "$BACKUP/worker.py"

restore() {
  cp "$BACKUP/parser.py" "$PARSER"
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/migration.py" "$MIGRATION"
  cp "$BACKUP/model.py" "$MODEL"
  cp "$BACKUP/worker.py" "$WORKER"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_bank_statement_rows.py
SHAPE=tests/backend/test_statement_row_shape.py
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

echo "== M10 slice 4 negative controls =="

# 1. Fold the digits before storing the raw copy. The single most tempting change in the parser:
#    the folded reading is the correct one, so why keep the other? Because §8.5's first rule is
#    "Preserve every raw source value", and this destroys the only copy of the bank's own text.
perl -0pi -e 's/        if \(text := _text\(cell, fold_digits=False\)\) is not None/        if (text := _text(cell, fold_digits=True)) is not None/' "$PARSER"
run "raw_data is folded before storage" "test_raw_and_normalized_values_are_both_kept" "$LIVE"

# 2. Convert the Jalali date with a plausible offset. Looks like completeness and writes an
#    unapproved timestamp into the column slice 5 matches on. ADR-006 has not chosen the
#    conversion, so any answer here is invented.
perl -0pi -e 's/    return None, \(\r?\n        "the date is Jalali and is preserved raw; ADR-006 leaves the calendar conversion "\r?\n        "undecided, so no instant is invented"\r?\n    \)/    return datetime(year - 979, month, day, hour, minute, second, tzinfo=UTC), None/' "$PARSER"
run "a Jalali date is converted anyway" "test_raw_and_normalized_values_are_both_kept" "$LIVE"

# 3. Round a fractional amount instead of refusing it. §8.5 rejects fractional IRR; rounding
#    invents a figure nobody wrote and the row then reads as clean.
perl -0pi -e 's/    if cleaned\.endswith\("\.0"\):\r?\n        cleaned = cleaned\[:-2\]/    if "." in cleaned:\n        cleaned = cleaned.split(".")[0]/' "$PARSER"
run "a fractional amount is rounded" "test_a_fractional_amount_is_flagged_and_not_rounded" "$LIVE"

# 4. Read the outgoing column as an incoming amount when the incoming one is blank. The single
#    most dangerous change in this slice: a withdrawal that reads as a deposit lets the centre
#    believe a trader paid when money left instead. §8.5 forbids it in one sentence.
perl -0pi -e 's/    amount_in, trouble = _amount\(by_field\.get\("amount_in_irr"\)\)/    amount_in, trouble = _amount(by_field.get("amount_in_irr") or by_field.get("amount_out_irr"))/' "$PARSER"
run "a debit is read as a credit" "test_a_debit_is_never_read_as_a_credit" "$LIVE"

# 5. Fingerprint the raw text rather than the normalized values. §8.4 calls it a *normalized*
#    fingerprint, and a digest over the raw text misses every duplicate a bank writes differently.
#
#    **This went NOT CAUGHT on the first run, and it was the fourth meaning: the test was
#    insensitive by construction.** The twin rows differed only in Persian versus ASCII digits,
#    and `app/core/hashing.py`'s `normalise_text` folds those on the way into *every* digest — so
#    both implementations produced the same answer and the hashing layer was silently supplying
#    the property under test. The twin now differs by a thousands separator, which `normalise_text`
#    does not touch and `_amount` does.
perl -0pi -e 's/    fingerprint = unversioned_digest\(\r?\n        \{/    fingerprint = unversioned_digest(raw_data) if True else unversioned_digest(\n        {/' "$PARSER"
run "the fingerprint is over the raw text" "test_two_identical_transfers_share_a_fingerprint" "$LIVE"

# 6. Drop the rows that could not be read. §22.2: "never partially hide invalid rows". The run's
#    row_count then silently disagrees with the file and nobody can see which lines went missing.
perl -0pi -e 's/    for parsed in result\.rows:\r?\n        session\.add\(_row_of\(run, parsed\)\)/    for parsed in result.rows:\n        if parsed.status == "invalid":\n            continue\n        session.add(_row_of(run, parsed))/' "$COMMANDS"
run "unreadable rows are silently dropped" "test_every_source_line_becomes_a_row" "$LIVE"

# 7. Write the rows a failed mapping managed to read. A partial statement that nothing marks as
#    partial is worse than none, because slice 5 will match against it.
perl -0pi -e 's/    except MappingConfigurationError as error:\r?\n        return _fail\(uow, run=run, statement=statement, now=now, reason=str\(error\)\)/    except MappingConfigurationError as error:\n        _fail(uow, run=run, statement=statement, now=now, reason=str(error))\n        run.status = RUN_SUCCEEDED\n        uow.flush()\n        return _report(run, [])/' "$COMMANDS"
run "a failed mapping reports success" "test_a_mapping_that_does_not_fit_fails_the_run" "$LIVE"

# 8. Accept any field name the mapping offers. The fixture that carries
#    `amount_irr"; DROP TABLE bank_mappings; --` exists for exactly this, and the allowlist is
#    what makes the value a string nobody executes.
perl -0pi -e 's/        if not isinstance\(name, str\) or name not in KNOWN_FIELDS:/        if not isinstance(name, str):/' "$PARSER"
run "an unknown mapping field is accepted" "test_a_mapping_naming_an_unknown_field" "$LIVE"

# 9. Grant the runtime UPDATE on a parsed row. Nothing behavioural changes — no code path updates
#    a row — and §10.6's "immutable" stops being a property of the database.
perl -0pi -e 's/    # \*\*No GRANT\.\*\*/    bind = op.get_bind()\n    from app.core.config import load_settings\n    for _role in (load_settings().app_db_role, load_settings().worker_db_role):\n        bind.execute(sa.text(f\x27GRANT UPDATE (status) ON public."bank_statement_rows" TO "{_role}"\x27))\n    # **No GRANT.**/' "$MIGRATION"
run "a parsed row becomes editable" "test_the_runtime_cannot_change_a_parsed_row" "$LIVE"

# 10. Add the polymorphic match flag document 04 refuses. Breaks no behaviour at all today: slice
#     5 would then write it in good faith, and two records would disagree about whether a row is
#     matched with the mutable one winning because it is easier to read.
#
#     **The first version of this pattern anchored on the comment above the column and matched
#     nothing.** It used `\S8\.4` to stand in for `§8.4`, and `§` is two bytes in UTF-8 while `\S`
#     matches one — so the control reported NOT CAUGHT while the file was untouched. The second
#     meaning, and the reason the rule is to diff before concluding. Anchored on the column
#     definition alone now, which is pure ASCII.
perl -0pi -e 's/^    row_fingerprint: Mapped\[str\] = mapped_column\(String\(64\), nullable=False\)$/    is_matched: Mapped[bool] = mapped_column(Boolean, nullable=False)\n    row_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)/m' "$MODEL"
perl -0pi -e 's/^from sqlalchemy import \($/from sqlalchemy import Boolean\nfrom sqlalchemy import (/m' "$MODEL"
run "a mutable is_matched flag is added" "test_no_polymorphic_match_column_exists" "$SHAPE"

# 11. Drop the raw date column from the model. Every parse still works and every behavioural test
#     still passes; the loss surfaces at the first mapping correction, when the string that would
#     have let the row be re-normalised turns out never to have been stored.
perl -0pi -e 's/    transaction_date_raw: Mapped\[str \| None\] = mapped_column\(String\(64\), nullable=True\)\r?\n//' "$MODEL"
run "the raw date is no longer stored" "test_raw_and_normalized_are_both_present_for_the_date" "$SHAPE"

# 12. Call a blank template line invalid. It fills an accountant's preview with problems that are
#     not problems, which is how a real problem stops being visible.
perl -0pi -e 's/            status=ROW_IGNORED_EMPTY,/            status=ROW_INVALID,/' "$PARSER"
run "a blank line is reported as invalid" "test_an_empty_line_is_ignored_rather_than_invalid" "$LIVE"

# 13. Leave the statement file `uploaded` after a successful parse. Document 06 §10.3 moves it to
#     `parsed` when a run succeeds, and a file that never advances is one nothing downstream can
#     tell apart from one nobody has parsed.
perl -0pi -e 's/    statement\.status = FILE_PARSED/    pass/' "$COMMANDS"
run "a parsed file stays uploaded" "test_every_source_line_becomes_a_row" "$LIVE"

# 14. Let the parse task fail a job type it does not recognise instead of handing it back. Two
#     tasks now share the `files` queue, and this exhausts a crop's attempts on a worker that
#     never tried it — the run would dead-letter having never been attempted.
perl -0pi -e 's/            for job in claimed:\r?\n                release_job\(job, status="retry_scheduled"\)\r?\n            uow\.commit\(\)\r?\n            return StatementParseReport\(parsed=0, failed=0\)/            for job in claimed:\n                release_job(job, status="dead_lettered")\n            uow.commit()\n            return StatementParseReport(parsed=0, failed=0)/' "$WORKER"
run "the parser dead-letters another task's job" "test_another_tasks_job_is_handed_back" "$LIVE"

echo "== done =="
