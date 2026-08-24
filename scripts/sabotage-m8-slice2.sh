#!/usr/bin/env bash
# Negative controls for M8 slice 2 — receipt segments.
#
# Six the plan names, and the second is the one worth reading: it removes the constraint that closes
# §12.4's own hole, and the test must fail on the partial rectangle the document admits.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

MODEL="services/backend/app/db/models/receipt_segment.py"
API="services/backend/app/api/v1/receipt_segments.py"
CMD="services/backend/app/commands/bank_result_bundle.py"
MIG="services/backend/alembic/versions/20260824_0024_receipt_segments.py"
BACKUP="$(mktemp -d)"

for pair in "MODEL model.py" "API api.py" "CMD cmd.py" "MIG mig.py"; do
  set -- $pair
  eval "cp \"\${$1}\" \"$BACKUP/$2\""
done

restore() {
  cp "$BACKUP/model.py" "$MODEL"
  cp "$BACKUP/api.py" "$API"
  cp "$BACKUP/cmd.py" "$CMD"
  cp "$BACKUP/mig.py" "$MIG"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
UNIT=tests/backend/test_segment_surface.py
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
    printf '  CAUGHT   %-46s' "$label"
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

echo "== M8 slice 2 negative controls =="

# 1. DB-SEGMENT-001. Let a rectangle run past the right edge — §12.4's own in-bounds branch.
perl -0pi -e 's/ AND bbox_x \+ bbox_width <= 1"/ AND bbox_x + bbox_width <= 2"/' "$MODEL"
perl -0pi -e 's/ AND bbox_x \+ bbox_width <= 1"/ AND bbox_x + bbox_width <= 2"/' "$MIG"
run "a rectangle may exceed the page width" "refuses_an_unreproducible_rectangle" "$LIVE"

# 2. DB-SEGMENT-001, the interesting half. Remove the all-or-nothing constraint and the partial
#    rectangle §12.4 admits comes back — three coordinates and a NULL fourth, accepted because a
#    CHECK that evaluates to NULL passes. The test must fail on exactly that case.
perl -0pi -e 's/        named_check\(\n            "num_nonnulls\(bbox_x, bbox_y, bbox_width, bbox_height\) IN \(0, 4\)",\n            name="bbox_is_all_or_nothing",\n        \),\n//' "$MODEL"
perl -0pi -e 's/        sa\.CheckConstraint\(\n            "num_nonnulls\(bbox_x, bbox_y, bbox_width, bbox_height\) IN \(0, 4\)",\n            name="bbox_is_all_or_nothing",\n        \),\n//' "$MIG"
run "the partial rectangle is allowed back" "half a rectangle" "$LIVE"

# 3. SVC-SEGMENT-001. Add the PATCH the permission catalogue forbids. Written as somebody would:
#    a route that looks careful, with a permission name that reads plausibly.
perl -0pi -e 's/(\@router\.get\(\n    "\/receipt-segments\/\{segment_id\}")/\@router.patch(\n    "\/receipt-segments\/{segment_id}",\n    response_model=SegmentDetail,\n    operation_id="patchReceiptSegment",\n    responses=RESPONSES,\n    dependencies=[requires(declare("receipt_segment.read"))],\n)\ndef patch_receipt_segment(segment_id: uuid.UUID) -> SegmentDetail:\n    raise NotFoundError()\n\n\n$1/' "$API"
run "a PATCH route appears" "no_route_can_patch_a_segment" "$UNIT"

# 4. SVC-SEGMENT-002. Let the creation request carry a rectangle. §12.4's CHECK would still hold,
#    which is the trap: a valid rectangle with no renderer behind it claims a crop never rendered.
perl -0pi -e 's/(    manual_fields: ManualFieldsRequest \| None = None)/    bbox_x: str | None = None\n$1/' "$API"
run "the creation request accepts a rectangle" "cannot_supply_a_rectangle" "$UNIT"

# 5. DB-SEGMENT-002. Name the feature-flagged method on the API surface, which is how a flag gets
#    bypassed: the value becomes reachable and the flag still reads as on.
#
#    The first version of this control built the string by concatenation to avoid writing it, and
#    produced a Python syntax error — reported as INVALID RUN rather than as a result, which is the
#    harness working. The simple sabotage is the realistic one anyway: somebody writes the literal.
perl -0pi -e 's/(SEGMENT_REDACTION = RedactionPolicy\(mask_iban=True\))/$1\nSABOTAGE_METHOD = "ai_auto_segmentation"/' "$API"
run "the AI method is named on the surface" "ai_creation_method_is_unreachable" "$UNIT"

# 6. SVC-SEGMENT-003. Increment the bundle count instead of recomputing it.
perl -0pi -e 's/    bundle\.segment_count = total/    bundle.segment_count = total + 1/' "$CMD"
run "the count is incremented, not recomputed" "recounts_the_bundle" "$LIVE"

echo "== done =="
