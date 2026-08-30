#!/usr/bin/env bash
# Negative controls for M9 slice 2 — confirmed evidence links.
#
# The slice rests on things the *database* enforces, so most of these break a constraint rather
# than a branch. Control 1 is the one worth reading: it removes a partial unique index and the
# concurrency test must fail — proving that test is about the index and not about the service.
#
# Every touched file is copied to a tempdir and restored from the copy. Never `git checkout --`:
# slice 1's script used it for one file and silently destroyed uncommitted work while every
# control still reported CAUGHT.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/confirmed_evidence_link.py"
MODEL="services/backend/app/db/models/confirmed_evidence_link.py"
ROUTES="services/backend/app/api/v1/evidence_links.py"
MIGRATION="services/backend/alembic/versions/20260830_0029_confirmed_evidence_links.py"
BACKUP="$(mktemp -d)"

cp "$COMMANDS" "$BACKUP/commands.py"
cp "$MODEL" "$BACKUP/model.py"
cp "$ROUTES" "$BACKUP/routes.py"
cp "$MIGRATION" "$BACKUP/migration.py"

restore() {
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/model.py" "$MODEL"
  cp "$BACKUP/routes.py" "$ROUTES"
  cp "$BACKUP/migration.py" "$MIGRATION"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_evidence_links.py
UNIT=tests/backend/test_evidence_link_schema.py
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
    printf '  CAUGHT   %-54s' "$label"
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

echo "== M9 slice 2 negative controls =="

# 1. Remove the attempt's partial unique index from the migration. The concurrency test must fail
#    — which is what proves that test is about the index rather than about anything in Python.
perl -0pi -e 's/    op\.create_index\(\r?\n        "uq_attempt_active_primary_evidence",(?:.|\n)*?\r?\n    \)\r?\n//' "$MIGRATION"
run "the attempt index is dropped" "test_two_concurrent_transactions_cannot_both" "$LIVE"

# 2. The other index. Asserted separately because the two constrain different columns, and a
#    copy-paste naming the same column twice would leave one of them unproved.
perl -0pi -e 's/    op\.create_index\(\r?\n        "uq_segment_active_primary_attempt",(?:.|\n)*?\r?\n    \)\r?\n//' "$MIGRATION"
run "the segment index is dropped" "test_a_segment_cannot_be_primary_evidence" "$LIVE"

# 3. Widen the attempt index's predicate so it also covers supplementary links. §17's third rule
#    is that supplementary evidence is unbounded, and it is expressed by an absence — this is what
#    an over-eager constraint looks like.
perl -0pi -e "s/postgresql_where=sa\.text\(\"link_type = 'primary' AND status = 'active'\"\),\r?\n    \)\r?\n    op\.create_index\(\r?\n        \"uq_segment_active_primary_attempt\"/postgresql_where=sa.text(\"status = 'active'\"),\n    )\n    op.create_index(\n        \"uq_segment_active_primary_attempt\"/" "$MIGRATION"
run "the index covers supplementary links too" "test_a_supplementary_link_does_not_displace" "$LIVE"

# 4. Insert the replacement before retiring the original — the order that seems natural and fails
#    against the very index the invariant depends on.
perl -0pi -e 's/    original\.status = LINK_REPLACED\r?\n    uow\.flush\(\)\r?\n//' "$COMMANDS"
run "the replacement is inserted before the retire" "test_a_replacement_retires_the_old_link" "$LIVE"

# 5. Delete the original instead of retiring it. §12.6 at `:1306` says replacement never deletes,
#    and the chain a later audit reads would simply be gone.
perl -0pi -e 's/    original\.status = LINK_REPLACED/    session.delete(original)/' "$COMMANDS"
run "the replacement deletes the old link" "test_a_replacement_retires_the_old_link" "$LIVE"

# 6. Let a primary link be voided. `:1864` routes it through replacement instead, and allowing it
#    leaves an attempt with no primary evidence and no replacement.
perl -0pi -e 's/    if link\.link_type != LINK_SUPPLEMENTARY:/    if False:/' "$COMMANDS"
run "a primary link can be voided" "test_a_primary_link_cannot_be_voided" "$LIVE"

# 7. Store the deprecated alias. The status catalogue makes `revoked` canonical, and the CHECK
#    admits only the canonical three — so this fails at the database as well as at the assertion.
perl -0pi -e 's/    link\.status = LINK_REVOKED/    link.status = "voided"/' "$COMMANDS"
run "the deprecated alias is stored" "test_voiding_stores_the_canonical_revoked_status" "$LIVE"

# 8. Publish an outbox event on confirmation. `command_catalog.yaml` gives that command
#    `outbox_event: null`, and an invented event is one no consumer contract names.
perl -0pi -e 's/(    _audit\(\r?\n        session,\r?\n        policy,\r?\n        names=CONFIRM_EVIDENCE_LINK,)/    OutboxWriter(session, policy).enqueue(\n        OutboxMessage(\n            aggregate_type="confirmed_evidence_link",\n            aggregate_id=link.id,\n            aggregate_version=1,\n            event_type="EvidenceLinkConfirmed",\n            payload={},\n            payload_version=1,\n            headers={},\n        )\n    )\n$1/' "$COMMANDS"
run "confirmation publishes an event" "test_each_command_writes_its_catalogued_action" "$LIVE"

# 9. Make `replaced` non-terminal, so a retired link could be revoked afterwards. Document 06's
#    diagram draws no arrow out of it.
perl -0pi -e 's/    LINK_REPLACED: frozenset\(\),/    LINK_REPLACED: frozenset({LINK_REVOKED}),/' "$MODEL"
run "a retired link can still be revoked" "test_the_workflow_document_draws_exactly" "$UNIT"

echo "== done =="
