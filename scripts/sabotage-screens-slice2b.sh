#!/usr/bin/env bash
# Negative controls for screens slice 2B — the export read shape.
#
# Three the plan names, plus three the survey suggested. Each must fail exactly one assertion.
#
# Restores from a byte copy, not `git checkout --`, which does nothing for a file git has never
# seen. And `git rev-parse` for the root, not `dirname $0`, because this is normally run from a
# line-ending-stripped copy under /tmp — resolving the root to `/` makes every control report a
# clean NOT CAUGHT while doing nothing at all.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

API="services/backend/app/api/v1/bank_exports.py"
CMD="services/backend/app/commands/bank_export.py"
TEST="tests/backend/test_export_read_shape.py"
BACKUP="$(mktemp -d)"

cp "$API" "$BACKUP/api.py"
cp "$CMD" "$BACKUP/cmd.py"
cp "$TEST" "$BACKUP/test.py"

restore() {
  cp "$BACKUP/api.py" "$API"
  cp "$BACKUP/cmd.py" "$CMD"
  cp "$BACKUP/test.py" "$TEST"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

PYTHON=services/backend/.venv/bin/python
SHAPE=tests/backend/test_export_read_shape.py
LIVE=tests/integration/test_export_download_and_sent.py

# The integration half needs a database, and a control that silently skipped would report NOT
# CAUGHT — the reading this harness exists to make impossible.
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

run() {
  local label="$1" expect="$2" target="${3:-$SHAPE}"
  local out
  out="$($PYTHON -m pytest "$target" -q 2>&1)"

  if printf '%s' "$out" | grep -qE '[0-9]+ skipped' && \
     ! printf '%s' "$out" | grep -qE '[0-9]+ (passed|failed)'; then
    printf '  SKIPPED — INVALID  %s\n' "$label"
    restore
    return
  fi

  # A run that never reached the tests is neither a pass nor a fail. Slice 2's harness reported
  # seven clean NOT CAUGHTs from a runner that crashed on startup, and that reading is worse than
  # no reading: it looks like seven insensitive tests instead of one broken command.
  if ! printf '%s' "$out" | grep -qE '[0-9]+ (passed|failed)'; then
    printf '  INVALID RUN  %s\n' "$label"
    printf '%s\n' "$out" | tail -4
    restore
    return
  fi

  if printf '%s' "$out" | grep -qE '[0-9]+ failed'; then
    printf '  CAUGHT   %-44s' "$label"
    if printf '%s' "$out" | grep -q "$expect"; then
      echo "(on: $expect)"
    else
      echo "*** WRONG ASSERTION *** expected: $expect"
      printf '%s\n' "$out" | grep -E "^(FAILED|tests/)" | head -6
    fi
  else
    printf '  NOT CAUGHT  %s\n' "$label"
  fi
  restore
}

echo "== screens slice 2B negative controls =="

# 1. API-EXPORTREAD-001. Drop one item §14.4 names. The plan's first named control.
perl -0pi -e 's/^    file_name: str$//m' "$API"
run "an item §14.4 names is dropped" "carries_every_item"

# 2. API-EXPORTREAD-003. Leave the export out of the comparison. This is the dangerous shape and
#    it reads perfectly well — "does the approval's hash match the version's" is a sentence
#    somebody would write for a field labelled "approval/hash match". It is also always true:
#    `fk_batch_approvals_approved_hash` makes the approval's hash the version's by construction, so
#    the field would report a match for a file rendered from anything at all.
#
#    The first attempt at this control compared the export against the *approval* instead of the
#    version, and was NOT CAUGHT — correctly. The same foreign key makes those two comparisons
#    equivalent for every reachable state, so that sabotage changed no behaviour. It was the
#    control that was wrong, not the test.
perl -0pi -e 's/            approval\.approved_content_hash == version\.content_hash\n            and export\.content_hash == version\.content_hash/            approval.approved_content_hash == version.content_hash/' "$API"
run "the export is left out of its own verdict" "computed_against_the_version" "$LIVE"

# 3. API-EXPORTREAD-002. Collapse the failed checks to a boolean, which cannot say which failed.
perl -0pi -e 's/    integrity_failed_checks: list\[str\]/    integrity_failed_checks: bool/' "$API"
run "failed checks collapsed to a boolean" "is_a_list_of_checks_not_a_boolean"

# 3b. The same obligation from the other side: return no failed checks at all for a broken file.
#     The field keeps its type, so the shape test passes and only the live test refuses.
perl -0pi -e 's/    return tuple\(failure\.describe\(\) for failure in failures\)/    return ()/' "$API"
run "a broken export reports nothing wrong" "names_each_failed_check" "$LIVE"

# 4. §14.7's asymmetry. Put the channel on the readable model, which is the change somebody makes
#    when a screen needs it later — and it means either a new column or reading an audit payload.
perl -0pi -e 's/(    generated_by: str \| None)/    submission_channel: str | None\n$1/' "$API"
run "channel becomes readable afterwards" "not_readable_afterwards"

# 5. The recorded absences lose their reason, which turns a considered gap into an exemption.
perl -0pi -e 's/^        "S-6\. It exists nowhere.*$/        "no reason",/m' "$TEST"
run "a recorded absence explains nothing" "carries_a_reason"

# 6. S-7 silently resolved in the fact gather but not in the plan or the display. This is the one
#    control that must fail *because the defect went away*: the pin exists so a fix cannot be
#    invisible.
perl -0pi -e 's/export_bank_account_id=version\.bank_account_id/export_bank_account_id=export.bank_profile_version_id/' "$CMD"
run "S-7 quietly changed" "cannot_disagree_for_a_stored_row"

echo "== done =="
