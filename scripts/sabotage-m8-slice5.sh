#!/usr/bin/env bash
# Negative controls for M8 slice 5 — previews.
#
# The plan names two: serve the source as the preview, and drop the permission check. Six more come
# from what the image path and the page count turned out to need.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

RENDER="services/backend/app/exports/crop.py"
PREVIEW="services/backend/app/files/preview.py"
FILES_API="services/backend/app/api/v1/files.py"
BUNDLE="services/backend/app/commands/bank_result_bundle.py"
BACKUP="$(mktemp -d)"

cp "$RENDER" "$BACKUP/render.py"
cp "$PREVIEW" "$BACKUP/preview.py"
cp "$FILES_API" "$BACKUP/files_api.py"
cp "$BUNDLE" "$BACKUP/bundle.py"

restore() {
  cp "$BACKUP/render.py" "$RENDER"
  cp "$BACKUP/preview.py" "$PREVIEW"
  cp "$BACKUP/files_api.py" "$FILES_API"
  cp "$BACKUP/bundle.py" "$BUNDLE"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
RENDERER=tests/backend/test_crop_renderer.py
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

echo "== M8 slice 5 negative controls =="

# 1. The plan's first. Serve the original bytes as the preview — which is not a hypothetical: it is
#    exactly what this route did from M4 until this slice. A preview that returns the source makes
#    the preview permission act as a download permission, and `05_API_Specification.md:1045` asks for
#    those to be separate.
perl -0pi -e 's/    return _preview\(runtime, actor, file_id, page_number=1, rotation_degrees=rotation_degrees\)/    return _stream(runtime, _authorized_file(runtime, actor, file_id))/' "$FILES_API"
run "the preview serves the original file" "never_the_original" "$LIVE"

# 2. The plan's second. Drop the ownership resolver from the page route, so any actor holding
#    `file.preview` can read any file. The trader is still refused at the permission gate — which is
#    why the control has to be aimed at the `warehouse_operator` case, and why a test using only a
#    trader would have reported NOT CAUGHT here and looked like a weak control.
perl -0pi -e 's/        if record is None or not may_access\(actor, _facts\(record\)\):/        if record is None:/' "$FILES_API"
run "the ownership resolver is skipped" "without_the_bundle_permission" "$LIVE"

# 3. Trust the caller's page count again — slice 1's behaviour, restored. The bundle then reports
#    whatever number was sent, and every screen that says "page 3 of 7" repeats it.
perl -0pi -e 's/                page_count=counted\[attachment\.file_id\],/                page_count=attachment.page_count,/' "$BUNDLE"
run "the page count is taken on trust" "documents_own" "$LIVE"

# 4. Resample the image rotation instead of permuting it. `Image.rotate` is the obvious-looking call
#    and it destroys the byte-equality claim: four quarter turns no longer return the original pixels,
#    so no rotated preview can be reproduced from its own provenance.
perl -0pi -e 's/    return image\.transpose\(turns\[rotation\]\)/    return image.rotate(rotation, expand=True)/' "$RENDER"
run "the image rotation resamples" "losslessly" "$RENDERER"

# 5. Turn the image the other way. Every rotation test that compares two renders to each other still
#    passes — this is the control that shows why one test has to look at where a pixel landed.
perl -0pi -e 's/        90: Image\.Transpose\.ROTATE_270,/        90: Image.Transpose.ROTATE_90,/' "$RENDER"
perl -0pi -e 's/        270: Image\.Transpose\.ROTATE_90,/        270: Image.Transpose.ROTATE_270,/' "$RENDER"
run "a clockwise turn goes anticlockwise" "goes_clockwise" "$RENDERER"

# 6. Apply the render scale to images too, which doubles a photograph and invents pixels the scanner
#    never recorded. The operator would then draw a rectangle on an interpolation.
perl -0pi -e 's/        width, height = _open_image\(document\)\.size/        _w, _h = _open_image(document).size\n        width, height = round(_w * RENDER_SCALE), round(_h * RENDER_SCALE)/' "$RENDER"
run "images are upscaled by the render scale" "not_upscaled" "$RENDERER"

# 7. Report the unrotated dimensions for a rotated page. The two numbers swap on a quarter turn, and
#    a client sending these as `client_source_dimensions` would have every crop refused — with the
#    message blaming the client for the server's arithmetic.
#
#    **Caught by the crop tests, not the preview ones, and that is the right answer.** It was aimed
#    at `API-PREVIEW-001` first and missed, because the preview headers are read off the rendered
#    image rather than from `page_size` — so no arithmetic error in that function can make them lie.
#    The consumer of `page_size` is the crop request's raster check, which is where this fires. Two
#    useful facts fell out of the miss: the preview dimensions are structurally trustworthy, and this
#    function has exactly one caller that can be wrong about it.
perl -0pi -e 's/    return \(height, width\) if rotation in \(90, 270\) else \(width, height\)/    return (width, height)/' "$RENDER"
run "rotated dimensions are not swapped" "rotated_raster" "$LIVE"

# 8. Never look in the cache, so every request renders and stores again. The reproducibility unique
#    refuses the second write, so the visible symptom is not two files but an error on the second
#    view of a page — which is worse, and is what the count assertion pins.
perl -0pi -e 's/    cached = _cached_derivation\(session, record\.id, parameters\)/    cached = None/' "$PREVIEW"
run "the derivation cache is never read" "renders_nothing_new" "$LIVE"

echo "== done =="
