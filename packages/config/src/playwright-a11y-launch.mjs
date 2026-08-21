/**
 * Chromium launch options for the accessibility suites in both apps.
 *
 * Shared rather than copied because the reason for the one flag below took a long
 * measurement to establish, and a flag without its reason is a flag somebody deletes.
 *
 * **Why `--disable-accelerated-2d-canvas`.** Every accessibility test in both apps began
 * timing out at Playwright's 30-second limit, on every branch, including commits that had
 * passed CI minutes earlier. Pages rendered and their `<h1>` was visible; only
 * `AxeBuilder.analyze()` hung. What it narrowed down to, in order:
 *
 * - 68 of the 69 rules in the suite's tag set finish together in 126ms. `color-contrast`
 *   alone does not finish in four minutes.
 * - Profiling the page's own isolate put 100% of samples in axe-core's `_isIconLigature`,
 *   which draws the first character of each text node into a canvas and counts pixels to
 *   decide whether the text is an icon font ligature.
 * - Instrumenting the canvas API: 24 `fillText` calls, and effectively the entire run inside
 *   one of them — a single Persian glyph on a 35x30 canvas. `measureText` and `getImageData`
 *   were microseconds. The page's own `performance.now()` also jumped 539 seconds inside a
 *   47-second window, so the renderer was stalling rather than computing.
 * - The identical `fillText` runs in 0ms in isolation, so neither the font nor the glyph is
 *   slow. `requestAnimationFrame` never fires here either — this environment produces no
 *   compositor frames, and a GPU-backed canvas that is drawn to and then read back is the
 *   one operation in the whole rule set that depends on that path.
 *
 * Three runs of each configuration, because one run cannot tell a fix from a coin flip:
 *
 * | flags                             | outcome                          |
 * | --------------------------------- | -------------------------------- |
 * | none (as the suite ran)           | stalled, stalled, stalled        |
 * | `--disable-gpu`                   | stalled, stalled, stalled        |
 * | `--disable-accelerated-2d-canvas` | 484ms, 532ms, 523ms — 0 findings |
 * | both together                     | stalled, stalled, stalled        |
 *
 * `--disable-gpu` does not help because Chromium then rasterises through SwiftShader, which
 * is the same accelerated canvas path. Only taking 2D canvas acceleration out fixes it.
 *
 * Applied unconditionally rather than behind an environment check, on purpose. CI has no GPU
 * and passes either way, so a conditional flag would mean the browser configuration differs
 * between a developer's machine and the job that gates the merge — and a local run that is
 * not the CI run is the thing that lets a failure through. The flag cannot weaken what is
 * being checked: accessibility findings do not depend on how pixels are rasterised, and the
 * suite reports the same zero findings with it as CI reports without it.
 *
 * @returns {{ args: string[], executablePath?: string }}
 */
export function a11yLaunchOptions() {
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;

  return {
    args: ["--disable-accelerated-2d-canvas"],
    ...(executablePath ? { executablePath } : {}),
  };
}
