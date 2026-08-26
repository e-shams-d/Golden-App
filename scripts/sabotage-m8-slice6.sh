#!/usr/bin/env bash
# Negative controls for M8 slice 6 — the review workspace.
#
# The plan names three: make the crop pointer-only, send pixel coordinates, remove the fallback.
# Five more come from what the screen turned out to depend on.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

MODULE="apps/admin-web/src/bundles.ts"
CANVAS="apps/admin-web/components/crop-canvas.tsx"
PREVIEW="apps/admin-web/components/page-preview.tsx"
PAGE="apps/admin-web/app/bank-result-bundles/[bundleId]/page.tsx"
NAV="apps/admin-web/src/navigation.ts"
BACKUP="$(mktemp -d)"

cp "$MODULE" "$BACKUP/module.ts"
cp "$CANVAS" "$BACKUP/canvas.tsx"
cp "$PREVIEW" "$BACKUP/preview.tsx"
cp "$PAGE" "$BACKUP/page.tsx"
cp "$NAV" "$BACKUP/nav.ts"

restore() {
  cp "$BACKUP/module.ts" "$MODULE"
  cp "$BACKUP/canvas.tsx" "$CANVAS"
  cp "$BACKUP/preview.tsx" "$PREVIEW"
  cp "$BACKUP/page.tsx" "$PAGE"
  cp "$BACKUP/nav.ts" "$NAV"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
OUT="$BACKUP/out.txt"

run() {
  local label="$1" expect="$2"
  pnpm --filter @gold/admin-web test > "$OUT" 2>&1

  # A crashed runner reports neither passed nor failed. Named rather than folded into either
  # outcome: the screens slice 2 harness called a crash a pass on all seven of its controls.
  if ! grep -qE 'Tests +[0-9]+ (passed|failed)|[0-9]+ (passed|failed)' "$OUT"; then
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
      grep -E '^ FAIL|×' "$OUT" | head -4
    fi
  else
    printf '  NOT CAUGHT  %s\n' "$label"
  fi
  restore
}

echo "== M8 slice 6 negative controls =="

# 1. The plan's first. Take the keyboard away from the crop, leaving only the drag — which excludes
#    anybody who cannot use a pointer from the one screen in this application built around one.
perl -0pi -e 's/          onKeyDown=\{onKeyDown\}\n//' "$CANVAS"
perl -0pi -e 's/(<fieldset className="grid grid-cols-2 gap-3 md:grid-cols-4">)/<fieldset hidden className="grid grid-cols-2 gap-3 md:grid-cols-4">/' "$CANVAS"
run "the crop is pointer-only" "keyboard"

# 2. The plan's second. Send the rectangle in pixels instead of normalised decimals. The server
#    stores `NUMERIC(10,6)` between 0 and 1, so this produces a crop refused for the whole page —
#    and the screen would look correct while every submission failed.
perl -0pi -e 's/    bbox: normalizeRectangle\(rectangle, raster\),/    bbox: { x: String(rectangle.x), y: String(rectangle.y), width: String(rectangle.width), height: String(rectangle.height) },/' "$MODULE"
run "pixel coordinates are sent" "normalized against the dimensions"

# 3. The plan's third. Remove the external-evidence fallback, so a bundle nothing can render becomes
#    a bundle nobody can work — §16 `:1069`'s last test, deleted.
perl -0pi -e 's/\{selected \? \(\n              <section aria-labelledby="external-evidence">/{false ? (\n              <section aria-labelledby="external-evidence">/' "$PAGE"
run "the evidence fallback is removed" "reachable whatever the preview does"

# 4. Hide the fallback behind a failed preview, which is the plausible version of removing it and
#    the one somebody would actually write. §16 `:1069`'s case is a preview that renders something
#    *useless*, not one that errors — so a fallback conditioned on failure is absent exactly when it
#    is needed.
perl -0pi -e 's/\{selected \? \(\n              <section aria-labelledby="external-evidence">/{selected \&\& !isPreviewable(selected) ? (\n              <section aria-labelledby="external-evidence">/' "$PAGE"
run "the fallback hides behind a failed preview" "reachable whatever the preview does"

# 5. Normalise against the displayed image rather than the rendered raster. This is the mistake the
#    whole module exists to prevent, and it is invisible at 100% zoom — which is where anybody
#    testing by hand would look.
perl -0pi -e 's/        const measured = rasterFrom\(response\.headers\);/        const measured = { pageNumber, rotationDegrees: rotation, pixelWidth: 1000, pixelHeight: 1000, rendererVersion: "x" };/' "$PREVIEW"
run "the raster is invented rather than read" "rather than the image element"

# 6. Let the rotation cycle by arithmetic, admitting angles the renderer refuses. `(current + 90) %
#    360` looks equivalent and accepts any starting value — including one from a query string.
perl -0pi -e 's/  return ROTATIONS\[\(ROTATIONS\.indexOf\(current\) \+ 1\) % ROTATIONS\.length\] \?\? 0;/  return ((current + 45) % 360) as Rotation;/' "$MODULE"
run "rotation leaves the four angles" "four angles the renderer accepts"

# 7. Let a nudge push the rectangle off the page. §12.4's CHECK refuses it, so the operator would
#    learn about the edge from a server error rather than from the edge not moving.
perl -0pi -e 's/    const x = clamp\(rectangle\.x \+ delta, 0, maxX - rectangle\.width\);\n    const y = clamp\(rectangle\.y \+ delta, 0, maxY - rectangle\.height\);/    const x = rectangle.x + delta;\n    const y = rectangle.y + delta;/' "$MODULE"
run "a nudge can leave the page" "never lets the rectangle leave"

# 8. Drop the queue from navigation, which is how the workspace became unreachable in the first
#    place — the state `UI-REQ-004` caught before this slice was finished.
perl -0pi -e 's/    href: "\/bank-result-bundles",/    href: "\/bank-result-bundles-missing",/' "$NAV"
run "the queue leaves the navigation" "gives every navigation item a page"

echo "== done =="
