#!/usr/bin/env bash
# Negative controls for M9 slice 7B — the correction.
#
# Controls 1 and 2 are POL-002's own obligation: "M9 correction and UAT must prove the control
# cannot be configured off." Each removes one half of the dual control, and neither half is
# sufficient on its own — the first alone would let two people without the grant correct, the
# second alone would let one person holding both.
#
# Control 5 is the hole this slice closed. It re-opens the ordinary replacement path against
# published evidence, which is what an accountant could do silently until now.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

CORRECTION="services/backend/app/commands/publication_correction.py"
LINKS="services/backend/app/commands/confirmed_evidence_link.py"
MIGRATION="services/backend/alembic/versions/20260903_0034_publication_correction_grant.py"
BACKUP="$(mktemp -d)"

cp "$CORRECTION" "$BACKUP/correction.py"
cp "$LINKS" "$BACKUP/links.py"
cp "$MIGRATION" "$BACKUP/migration.py"

restore() {
  cp "$BACKUP/correction.py" "$CORRECTION"
  cp "$BACKUP/links.py" "$LINKS"
  cp "$BACKUP/migration.py" "$MIGRATION"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_publication_correction.py
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

echo "== M9 slice 7B negative controls =="

# 1. Let one person be both preparer and approver. POL-002 rejects the accountant-only default
#    outright, and this is the form it takes when an administrator grants both roles.
perl -0pi -e 's/    if command\.prepared_by_admin_user_id == command\.approved_by_admin_user_id:/    if False:/' "$CORRECTION"
run "one human is both halves" "test_one_person_holding_both_permissions_is_still" "$LIVE"

# 2. Stop checking that the named approver holds the grant. An accountant could then approve their
#    own correction by typing any colleague's id.
perl -0pi -e 's/    _refuse_an_approver_without_the_grant\(uow\.session, command\)\r?\n//' "$CORRECTION"
run "the approver need not hold the grant" "test_a_named_approver_must_hold_the_grant" "$LIVE"

# 3. Delete publication N instead of superseding it. §17.7's second step and
#    `04_Database_Schema.md:1162` both require the old version to survive.
perl -0pi -e 's/    active\.status = PUBLICATION_SUPERSEDED/    session.delete(active)/' "$CORRECTION"
run "publication N is deleted" "test_publication_n_survives_byte_for_byte" "$LIVE"

# 4. Leave N active while inserting N+1. `uq_active_publication_per_request` refuses it, so this
#    proves the constraint is reached rather than that the code remembers to supersede.
perl -0pi -e 's/    active\.status = PUBLICATION_SUPERSEDED/    pass/' "$CORRECTION"
run "two publications stay active" "test_a_correction_creates_n_plus_one" "$LIVE"

# 5. Re-open the hole: let the ordinary replacement route retire evidence a trader has been shown.
perl -0pi -e 's/    _refuse_to_replace_evidence_a_trader_has_seen\(session, original\)\r?\n//' "$LINKS"
run "published evidence is replaceable again" "test_the_ordinary_replacement_route_refuses" "$LIVE"

# 6. Widen the grant. The payload and the hash become writable, and "the previous version is
#    preserved" stops being a property of the database.
#
#    Pointed at the *privilege* test, not the behavioural one. The first version aimed this at
#    `test_publication_n_survives_byte_for_byte` and went NOT CAUGHT — correctly: the command does
#    not write those columns, so widening what it *may* write changed nothing observable. A grant
#    is a capability, and only a query about privileges can see one.
#    `test_the_runtime_may_update_only_the_publication_status` exists because of this control.
perl -0pi -e 's/GRANTED_COLUMNS = \("status",\)/GRANTED_COLUMNS = ("status", "summary_payload", "content_hash")/' "$MIGRATION"
run "the correction grant is widened" "test_the_runtime_may_update_only_the_publication" "$LIVE"

# 7. Skip the identical-content check. The unique index still refuses the row, but only after N is
#    superseded — so the caller gets a duplicate-key error and the transaction unwinds.
perl -0pi -e 's/    if content_hash == active\.content_hash:/    if False:/' "$CORRECTION"
run "an unchanged correction reaches the index" "test_a_correction_that_changes_nothing_is_refused" "$LIVE"

# 8. Audit only the calling session. A dual-control decision recorded as one person's act cannot
#    answer the one question anybody asks afterwards.
perl -0pi -e 's/                "approved_by_admin_user_id": str\(command\.approved_by_admin_user_id\),\r?\n//' "$CORRECTION"
run "the audit row hides the approver" "test_a_correction_audits_both_humans" "$LIVE"

# 9. Point the corrected publication at the retired link. Publication N+1 would then cite evidence
#    that is `replaced`, and the traceability chain would resolve to the wrong row.
perl -0pi -e 's/        primary_evidence_link_id=evidence\.id,/        primary_evidence_link_id=supersedes.primary_evidence_link_id,/' "$CORRECTION"
run "N+1 cites the retired evidence" "test_every_published_result_traces_back" "$LIVE"

echo "== done =="
