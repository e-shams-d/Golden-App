#!/usr/bin/env bash
# Negative controls for M8 slice 4 — the in-panel crop.
#
# The plan names three: store the bbox without the rotation, write the crop over the source, and let
# the render succeed twice. Four more follow from what the code turned out to guard — the client's
# raster, the lifecycle check, the renderer-version agreement, and the scale.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

CMD="services/backend/app/commands/receipt_crop.py"
RENDER="services/backend/app/exports/crop.py"
WORKER="services/backend/app/workers/tasks/files.py"
BACKUP="$(mktemp -d)"

cp "$CMD" "$BACKUP/cmd.py"
cp "$RENDER" "$BACKUP/render.py"
cp "$WORKER" "$BACKUP/worker.py"

restore() {
  cp "$BACKUP/cmd.py" "$CMD"
  cp "$BACKUP/render.py" "$RENDER"
  cp "$BACKUP/worker.py" "$WORKER"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
UNIT=tests/backend/test_crop_command_shape.py
RENDERER=tests/backend/test_crop_renderer.py
LIVE=tests/integration/test_segment_intake.py
OUT="$BACKUP/out.txt"

run() {
  local label="$1" expect="$2" target="$3"
  "$PYTHON" -m pytest "$target" -q > "$OUT" 2>&1

  # A crashed runner reports neither. Slice 2's harness called a crash a pass on all seven controls,
  # so the invalid case is named rather than folded into either outcome.
  if ! grep -qE '[0-9]+ (passed|failed)' "$OUT"; then
    printf '  INVALID RUN  %s\n' "$label"
    tail -4 "$OUT"
    restore
    return
  fi
  if grep -qE '[0-9]+ failed' "$OUT"; then
    printf '  CAUGHT   %-48s' "$label"
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

echo "== M8 slice 4 negative controls =="

# 1. The plan's first, and DOC-CONFLICT-057's whole argument. Store every crop as upright: the row
#    keeps its four coordinates and forgets the angle they were drawn at. The rectangle is still
#    perfectly valid, the crop still renders, and the stored provenance now describes a different
#    region of the page — which is the failure that is invisible without the reproduction test.
perl -0pi -e 's/        rotation_degrees=command\.rotation_degrees,\n        source_pixel_width/        rotation_degrees=0,\n        source_pixel_width/' "$CMD"
run "the rotation is not stored" "reproduces_the_crop" "$LIVE"

# 2. The plan's second. Write the derived crop over the source key instead of a new one, which is the
#    single most destructive thing this slice could do: the bundle's evidence would be replaced by a
#    picture of part of itself, and every other segment on that file would silently become wrong.
#
#    Sabotaged in `record_derivation`'s caller rather than in the helper, because the helper is M4's
#    and its own tests would catch it — the question here is whether *this* slice would notice.
perl -0pi -e 's/    after = measure_now\(storage, source\)\n    if before != after:/    import io as _io\n    storage.write(source.storage_key, _io.BytesIO(rendered.content))\n    after = measure_now(storage, source)\n    if before != after:/' "$CMD"
run "the crop is written over the source" "untouched_by_its_own_crop" "$LIVE"

# 3. The plan's third. Remove the already-rendered early return, so a second render of one segment
#    stores a second file — two objects claiming to be the same evidence, with nothing saying which
#    one an auditor should look at.
#
#    **Aimed at the direct test, and the first aim was wrong in a way worth recording.** Pointed at
#    the worker this reported NOT CAUGHT, and the control was right: the worker's idempotency comes
#    from the job, not from this guard. After a success the job is `succeeded`, so a second pass
#    claims nothing and never reaches the return. Two independent protections, and the queue-level
#    one was hiding the command-level one — so the test that reaches this guard calls
#    `render_pending_crop` directly, which is how slice 6 and any repair path will call it.
perl -0pi -e 's/    if segment\.segment_file_id is not None:/    if False:/' "$CMD"
run "a second render makes a second file" "twice_makes_one_file" "$LIVE"

# 4. Drop the client-raster check. Every coordinate a caller sends is still validated against 0..1,
#    so this sabotage leaves a system that accepts well-formed rectangles describing regions nobody
#    selected — the one error §16.4's own list does not ask anybody to catch.
perl -0pi -e 's/    if \(command\.client_source_width, command\.client_source_height\) != raster:/    if False:/' "$CMD"
run "the client's raster is not checked" "wrong_raster_is_refused" "$LIVE"

# 5. `SVC-CROP-006`. Accept any scan status, which is how a quarantined file becomes evidence. The
#    storage-status half of the guard stays, so this control also shows the two conditions are not
#    redundant: a file can be `available` and not clean at the moment a verdict lands.
perl -0pi -e 's/    if source\.scan_status != CLEAN_SCAN_STATUS:/    if False:/' "$CMD"
run "a quarantined source is croppable" "quarantined_source_cannot_be_cropped" "$LIVE"

# 6. Let the renderer version drift. Accepting a render from a version the row does not name produces
#    a file whose provenance describes software that did not make it, and `SVC-CROP-004` would then
#    assert reproduction against a renderer nobody can reproduce with.
#
#    **Only the guard is sabotaged, and the first version of this control also rewrote
#    `RENDERER_VERSION`.** That reported NOT CAUGHT, correctly: the constant is read both when the
#    request stores the provenance and when the worker renders, so changing it changes both and they
#    still agree. No edit to that constant can create drift — only a deploy between two moments can,
#    which is what the test simulates from the owner connection.
perl -0pi -e 's/    if segment\.renderer_version != rendered\.renderer_version:/    if False:/' "$CMD"
run "the renderer version may drift" "renderer_upgrade" "$LIVE"

# 7. Make the render scale a per-request value by doubling it in the renderer. Every stored crop's
#    provenance keeps saying 2.0 while the pixels come from 4.0, so re-rendering from the row
#    produces a different image at every size.
#    Caught by the control test — the one asserting `RENDER_SCALE == 2.0` and the page's rasterised
#    size — which is the right place: every other assertion in that file is relative to whatever the
#    scale happens to be, so the scale is the one thing that has to be pinned absolutely.
perl -0pi -e 's/^RENDER_SCALE = 2\.0$/RENDER_SCALE = 4.0/m' "$RENDER"
run "the render scale changes" "document_opens_and_reports_its_pages" "$RENDERER"

# 8. The prohibition test's own control. Import a payment attempt into the crop command — the one
#    §16.5 prohibition that names something this milestone can actually reach.
perl -0pi -e 's/^from app\.db\.models\.processing_job import ProcessingJob$/from app.db.models.payment_batch import PaymentAttempt\nfrom app.db.models.processing_job import ProcessingJob/m' "$CMD"
run "the crop command imports PaymentAttempt" "must_not_do" "$UNIT"

echo "== done =="
