#!/usr/bin/env bash
# Negative controls for M9 slice 5 — publication.
#
# Controls 1 and 2 are the ones that matter, and they attack the same property from both ends:
# put the clock into the hashed payload, or the version counter, and
# `UNIQUE(payment_request_id, content_hash)` can never fire again while remaining visible in every
# schema report. A test that published once would pass against either.
#
# Control 4 is the other kind: it makes the publication fall back to the bank's bundle when a
# segment has no crop. That is a helpful-looking change and it is precisely how every trader's
# results reach one trader.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/payment_publication.py"
MIGRATION="services/backend/alembic/versions/20260831_0031_payment_result_publications.py"
ROUTES="services/backend/app/api/v1/payment_publications.py"
BACKUP="$(mktemp -d)"

cp "$COMMANDS" "$BACKUP/commands.py"
cp "$MIGRATION" "$BACKUP/migration.py"
cp "$ROUTES" "$BACKUP/routes.py"

restore() {
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/migration.py" "$MIGRATION"
  cp "$BACKUP/routes.py" "$ROUTES"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_payment_publications.py
SHAPE=tests/backend/test_publication_shape.py
ISOLATION=tests/backend/test_trader_surface_isolation.py
PRIVACY=tests/backend/test_privacy_and_no_ai.py
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

echo "== M9 slice 5 negative controls =="

# 1. Put the publication timestamp into the hashed payload. Every republication is then unique by
#    its clock and `uq_publication_content_per_request` refuses nothing, forever.
perl -0pi -e 's/(        "request_number": request\.request_number,\r?\n)/$1        "published_at": __import__("datetime").datetime.now().isoformat(),\n/' "$COMMANDS"
run "the clock is inside the hash" "test_the_hashed_payload_contains_no_key" "$SHAPE"

# 2. The same failure through the counter rather than the clock, and a different test must catch
#    it — the AST scan reads keys, so a version key is as fatal as a timestamp.
perl -0pi -e 's/(        "request_number": request\.request_number,\r?\n)/$1        "publication_version": 1,\n/' "$COMMANDS"
run "the version counter is inside the hash" "test_the_hashed_payload_contains_no_key" "$SHAPE"

# 3. Store the beneficiary IBAN unmasked. §17 `:1153` requires it masked, and a JSONB column
#    retained for years is the worst place in the system to keep a full account number.
perl -0pi -e 's/mask_iban_value\(revision\.beneficiary_iban_snapshot\)/revision.beneficiary_iban_snapshot/' "$COMMANDS"
run "the full IBAN is stored" "test_the_snapshot_is_derived_and_masks_the_iban" "$LIVE"

# 4. Fall back to the bank's bundle when a segment has no crop. Helpful-looking, and it is exactly
#    how every trader's results reach one trader.
perl -0pi -e 's/    if segment\.segment_file_id is None:\r?\n(.|\n)*?    return segment\.segment_file_id/    if segment.segment_file_id is None:\n        return segment.source_file_id\n    return segment.segment_file_id/' "$COMMANDS"
run "a missing crop falls back to the bundle" "test_the_publication_snapshot_reads_only_the_crop" "$ISOLATION"

# 5. Grant the runtime UPDATE on the publication table. §11.9's "immutable" becomes a description
#    of intent rather than of the database.
perl -0pi -e 's/(def downgrade\(\) -> None:)/def _grant(bind: object) -> None:\n    bind.execute(  # type: ignore[attr-defined]\n        sa.text(\x27GRANT UPDATE ON public."payment_result_publications" TO "app"\x27)\n    )\n\n\n$1/' "$MIGRATION"
run "the migration grants UPDATE" "test_the_migration_grants_no_update" "$SHAPE"

# 6. Accept an evidence link belonging to another payment request. Active, real, and somebody
#    else's — the isolation failure that arrives through a legitimate-looking field.
perl -0pi -e 's/    if attempt\.payment_request_id != request\.id:/    if False:/' "$COMMANDS"
run "another request's evidence is accepted" "test_evidence_from_another_request_is_refused" "$LIVE"

# 7. Publish straight from `paid`, skipping the preview. The validation step that stands between a
#    bad snapshot and a trader disappears, and 13.2 has no such arrow.
perl -0pi -e 's/    if request\.status not in PUBLISHABLE_FROM:/    if False:/' "$COMMANDS"
run "publishing skips the preview" "test_a_request_that_was_not_previewed" "$LIVE"

# 8. Let a `partially_paid` request be previewed. Document 06 draws no arrow, and a trader would
#    be shown a "result" for money that is still partly outstanding.
perl -0pi -e 's/    if request\.status not in PREVIEWABLE_FROM:/    if False:/' "$COMMANDS"
run "a partially paid request is previewable" "test_a_partially_paid_request_cannot_be_previewed" "$LIVE"

# 9. Stop marking the evidence as published. The column slice 2 created for this slice goes back
#    to being written by nothing.
perl -0pi -e 's/        link\.published_to_trader_at = now/        pass/' "$COMMANDS"
run "the evidence is never marked published" "test_publishing_marks_the_evidence_as_seen" "$LIVE"

# 10. Offer a share file the renderer does not exist for. A flag that changes nothing reads as a
#     working feature — the mechanism-with-no-caller defect, inverted.
perl -0pi -e 's/(    primary_evidence_link_id: uuid\.UUID \| None = None\r?\n    message_to_trader)/    include_share_file: bool = False\n$1/' "$ROUTES"
run "an unimplemented share file can be ordered" "test_neither_body_offers_a_share_file" "$SHAPE"

# 11. Copy the whole payload into the audit row. A trader's financial detail lands in a second
#     retained place for no gain, which the audit assertion names explicitly.
perl -0pi -e 's/(                "content_hash": publication\.content_hash,\r?\n)/$1                **publication.summary_payload,\n/' "$COMMANDS"
run "the audit row duplicates the payload" "test_publishing_records_an_audit_row" "$LIVE"

# 12. Drop the privacy guard. §19.3's sixth guard, and the caller M8 built a mechanism for and
#     could not write — evidence nobody reviewed goes straight to a trader.
perl -0pi -e 's/    _refuse_unverified_privacy\(session, link\)\r?\n//g' "$COMMANDS"
run "evidence is published unreviewed" "test_evidence_with_no_privacy_review_cannot" "$LIVE"

# 13. The same guard, defeated more quietly: read the *task's* version instead of comparing it to
#     the segment's, so a review of version 1 keeps passing after a re-render.
perl -0pi -e 's/    if not verification\.verified:/    if verification.task_id is None:/' "$COMMANDS"
run "a stale review still counts" "test_a_review_of_an_earlier_segment_version" "$LIVE"

# 14. Trust the request's derived status instead of the confirming actor. §19.3's first guard asks
#     whether a *person* confirmed; a computed status cannot answer that.
perl -0pi -e 's/            PaymentAttempt\.confirmed_by_admin_user_id\.is_not\(None\),\r?\n//' "$COMMANDS"
run "a status vouches for a person" "test_a_result_no_person_confirmed_cannot" "$LIVE"

# 15. Ignore the caller's expected version. §19.3's eighth guard, and the publication becomes a
#     snapshot of a request that may have moved since the accountant read it.
perl -0pi -e 's/        expected_version=command\.expected_record_version,/        expected_version=request.record_version,/' "$COMMANDS"
run "the expected version is ignored" "test_a_stale_if_match_refuses_the_publication" "$LIVE"

# 16. Publish a field from the router, bypassing the one module that performs the privacy check.
#     The narrowed keyword rule must still catch a real ORM write — if it does not, narrowing it
#     opened a hole rather than closing a false positive.
perl -0pi -e 's/(from app\.security\.permissions import declare\r?\n)/$1from app.db.models.payment_result_publication import PaymentResultPublication\n/' "$ROUTES"
perl -0pi -e 's/(def _audit_actor\(actor: ActorContext\) -> AuditActor:)/def _tamper() -> object:\n    return PaymentResultPublication(published_at=None)\n\n\n$1/' "$ROUTES"
run "the router writes a publication field" "test_only_the_publication_command_assigns" "$PRIVACY"

# 17. Widen publication to `failed`, the edit G-5 exists to make deliberate. A failure has no
#     evidence to carry and no share file to produce; it is notified, not published.
perl -0pi -e 's/^PREVIEWABLE_FROM: tuple\[str, \.\.\.\] = \("paid", "result_ready_for_trader"\)/PREVIEWABLE_FROM: tuple[str, ...] = ("paid", "failed", "result_ready_for_trader")/m' "$COMMANDS"
run "publication widened to failed" "test_publication_is_reachable_only_from_paid" "$SHAPE"

echo "== done =="
