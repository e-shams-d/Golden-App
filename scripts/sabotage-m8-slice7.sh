#!/usr/bin/env bash
# Negative controls for M8 slice 7 — privacy review and the Definition of Done.
#
# The plan names three: add a publishable flag, leave a verification attached across an edit,
# register the AI extraction route. Four more come from what the slice turned out to rest on.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

TASKS="services/backend/app/commands/manual_review_task.py"
CROP="services/backend/app/commands/receipt_crop.py"
SEGMENTS_API="services/backend/app/api/v1/receipt_segments.py"
ROUTER="services/backend/app/api/router.py"
BACKUP="$(mktemp -d)"

cp "$TASKS" "$BACKUP/tasks.py"
cp "$CROP" "$BACKUP/crop.py"
cp "$SEGMENTS_API" "$BACKUP/segments_api.py"
cp "$ROUTER" "$BACKUP/router.py"

restore() {
  cp "$BACKUP/tasks.py" "$TASKS"
  cp "$BACKUP/crop.py" "$CROP"
  cp "$BACKUP/segments_api.py" "$SEGMENTS_API"
  cp "$BACKUP/router.py" "$ROUTER"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
UNIT=tests/backend/test_privacy_and_no_ai.py
LIVE=tests/integration/test_segment_intake.py
OUT="$BACKUP/out.txt"

run() {
  local label="$1" expect="$2" target="$3"
  "$PYTHON" -m pytest "$target" -q > "$OUT" 2>&1

  if ! grep -qE '[0-9]+ (passed|failed)' "$OUT"; then
    printf '  INVALID RUN  %s\n' "$label"
    tail -4 "$OUT"
    restore
    return
  fi
  if grep -qE '[0-9]+ failed' "$OUT"; then
    printf '  CAUGHT   %-50s' "$label"
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

echo "== M8 slice 7 negative controls =="

# 1. The plan's first. Give the segment surface a way to mark a crop publishable — which is the whole
#    of what §16.5 stands between: publication without a privacy check.
perl -0pi -e 's/def _detail\(segment: ReceiptSegment, session: Session\) -> SegmentDetail:/def mark_publishable(segment: ReceiptSegment) -> None:\n    segment.published = True\n\n\ndef _detail(segment: ReceiptSegment, session: Session) -> SegmentDetail:/' "$SEGMENTS_API"
run "a publishable setter appears" "writes a publication field" "$UNIT"

# 2. The plan's second. Keep the verification attached across a change to the segment, by comparing
#    nothing — the stored-flag version of this feature. The screen would then say "verified" about an
#    image nobody looked at.
perl -0pi -e 's/        verified=task\.entity_record_version == segment\.record_version,/        verified=True,/' "$TASKS"
run "a verification survives an edit" "unverified_again" "$LIVE"

# 3. The plan's third. Register doc 05 :1721's AI extraction route, which §1.4 says this milestone
#    does not build.
perl -0pi -e 's/(router = APIRouter\(tags=\["receipt-segments"\]\))/$1\n\n\n\@router.post("\/receipt-segments\/{segment_id}\/ai-extraction", operation_id="aiExtract")\ndef ai_extract(segment_id: uuid.UUID) -> dict[str, str]:\n    return {"status": "queued"}/' "$SEGMENTS_API"
run "the AI extraction route is registered" "AI extraction route is served" "$UNIT"

# 4. Stop recording the version at all, so a verification says only "somebody looked at this segment
#    once". `SVC-PRIVACY-001` asks for four facts and this removes the fourth.
perl -0pi -e 's/    task\.entity_record_version = _subject_version\(session, task\)/    pass/' "$TASKS"
run "the verified version is not recorded" "who_when_and_which_version" "$LIVE"

# 5. Treat `unresolved_with_reason` as a pass, which would make the honest disposition the dangerous
#    one: an operator writing "this shows another customer's IBAN" would thereby approve it.
perl -0pi -e 's/            ManualReviewTask\.resolution_code != RESOLUTION_UNRESOLVED,\r?\n//' "$TASKS"
run "an unresolved close counts as verified" "verifies_nothing" "$LIVE"

# 6. Stop raising the privacy task when a crop is made, so §16.5's obligation depends on somebody
#    remembering it. Nothing else in the system would ever ask.
perl -0pi -e 's/    open_task\(\r?\n        OpenTask\(\r?\n            task_type=TASK_TYPE_PRIVACY_REVIEW,/    _skipped = lambda *a, **k: None\n    _skipped(\n        OpenTask(\n            task_type=TASK_TYPE_PRIVACY_REVIEW,/' "$CROP"
run "a crop raises no privacy task" "nobody_has_to_remember" "$LIVE"

# 7. Let the AI creation method be written by the crop command. The CHECK admits the value — doc 04
#    lists it — so nothing at the database level refuses this, which is exactly why the assertion is
#    over the source.
perl -0pi -e 's/        creation_method=METHOD_CROP,/        creation_method="ai_auto_segmentation",/' "$CROP"
run "the AI creation method is written" "appears as a literal" "$UNIT"

# 8. Return the privacy state as a constant rather than a comparison, which is the plausible
#    shortcut: it makes every segment look checked and the journey test still walks to the end.
perl -0pi -e 's/    privacy_verified=verification\.verified,/    privacy_verified=True,/' "$SEGMENTS_API"
run "the screen is told everything is verified" "unverified_again" "$LIVE"

echo "== done =="
