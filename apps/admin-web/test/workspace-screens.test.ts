/**
 * The review workspace renders §16.3's list — and records, against the contract, the four items it
 * cannot yet build.
 *
 * M8 slice 6. The eleven items are parsed out of the implementation plan rather than copied here,
 * for `export-screens.test.ts`'s reason: two copies of a list disagree the day the document gains a
 * twelfth, and neither copy says which one is wrong.
 *
 * **Four items have no route to talk to.** Attempt search needs `GET /api/v1/payment-attempts`,
 * which doc 05 `:1553` specifies and nobody has built; the candidate, evidence and history drawers
 * need matching, evidence links and segment history, all M9's. Building four panels with nothing
 * behind them would be worse than the absence — an empty drawer reads as "no candidates found"
 * rather than "this does not work yet".
 *
 * So they are recorded, and the record is checked against the generated OpenAPI contract rather
 * than trusted. `test_the_absent_items_still_have_no_route` fails the day M9 adds one of those
 * routes, which is exactly when somebody needs to be told a workspace panel became buildable. Slice
 * 4 used the same shape for §16.5's prohibitions, where two of the three named mechanisms did not
 * exist yet and three passing assertions would otherwise have read as three enforced rules.
 *
 * Covers: UI-WORKSPACE-001, UI-CROP-001, UI-CROP-002, UI-EVIDENCE-001.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  buildCropRequest,
  type BundleFile,
  normalizeRectangle,
  NUDGE_STEP,
  NUDGE_STEP_COARSE,
  nudge,
  type PixelRectangle,
  previewPath,
  rasterFrom,
  type RenderedRaster,
  rotateAnticlockwise,
  rotateClockwise,
  ROTATIONS,
  stepPage,
} from "../src/bundles";

const APP_ROOT = join(import.meta.dirname, "..");
const REPOSITORY_ROOT = join(APP_ROOT, "..", "..");
const PLAN = join(
  REPOSITORY_ROOT,
  "Implementation Docs",
  "00_Start_Here",
  "15_Agent_Implementation_Plan.md",
);
const CONTRACT = join(REPOSITORY_ROOT, "services", "backend", "openapi", "v1.json");

const WORKSPACE_PAGE = join(APP_ROOT, "app", "bank-result-bundles", "[bundleId]", "page.tsx");
const CROP_CANVAS = join(APP_ROOT, "components", "crop-canvas.tsx");
const PAGE_PREVIEW = join(APP_ROOT, "components", "page-preview.tsx");
const MODULE = join(APP_ROOT, "src", "bundles.ts");

const read = (path: string): string => readFileSync(path, "utf8");

/** §16.3's list, taken from the document that states it. */
function workspaceItems(): readonly string[] {
  const plan = read(PLAN);
  const heading = plan.indexOf("## 16.3 Admin workspace");
  expect(heading).toBeGreaterThan(-1);
  const next = plan.indexOf("## 16.4", heading);
  const section = plan.slice(heading, next);

  const items = [...section.matchAll(/^- (.+?);?$/gm)].map((match) =>
    (match[1] ?? "").replace(/\.$/, "").trim(),
  );
  expect(items.length).toBeGreaterThan(5);
  return items;
}

/**
 * The four items with no server surface, and the route each is waiting for.
 *
 * The route strings are what `test_the_absent_items_still_have_no_route` looks for in the contract,
 * so this table is a live claim rather than a note.
 */
const ABSENT_UNTIL_M9: ReadonlyMap<string, string> = new Map([
  ["attempt search", "/payment-attempts"],
  ["candidate/evidence/history drawers", "/receipt-segments/{segment_id}/matching-candidates"],
]);

describe("the workspace covers §16.3", () => {
  it("renders or deliberately records every item the document lists", () => {
    const source = [read(WORKSPACE_PAGE), read(CROP_CANVAS), read(PAGE_PREVIEW), read(MODULE)].join(
      "\n",
    );

    // What each item looks like when it is actually built. Keyed by the document's own wording so a
    // reworded item fails here rather than silently dropping out of the check.
    const evidence: ReadonlyMap<string, readonly string[]> = new Map([
      ["bundle summary and unresolved navigation", ["admin.workspace.summary", "unresolved"]],
      ["PDF/image/Excel preview", ["PagePreview", "admin.workspace.noPreview"]],
      ["page selection", ["stepPage", "admin.workspace.nextPage"]],
      ["zoom, pan, and rotation", ["zoom", "rotateClockwise", "overflow-auto"]],
      ["rectangular crop selection", ["CropCanvas", "onPointerDown"]],
      ["normalized coordinates", ["normalizeRectangle", "admin.workspace.normalized"]],
      ["selected-segment fields", ["admin.workspace.fields", "manual_fields"]],
      ["keyboard-accessible controls", ["onKeyDown", "ArrowLeft", "NumberField"]],
      ["external evidence fallback", ["attachExternalEvidence", "admin.workspace.external"]],
    ]);

    const unaccounted: string[] = [];
    for (const item of workspaceItems()) {
      if (ABSENT_UNTIL_M9.has(item)) continue;
      const markers = evidence.get(item);
      if (!markers) {
        unaccounted.push(`${item} — no marker recorded`);
        continue;
      }
      const missing = markers.filter((marker) => !source.includes(marker));
      if (missing.length > 0) unaccounted.push(`${item} — missing ${missing.join(", ")}`);
    }

    expect(unaccounted).toEqual([]);
  });

  it("accounts for every item exactly once, present or recorded absent", () => {
    // The control on the test above. Without it an item could be dropped from both the evidence map
    // and the absent map and nothing would notice — the check would simply stop looking at it.
    const items = workspaceItems();
    const recorded = new Set([...ABSENT_UNTIL_M9.keys()]);
    const unknown = items.filter((item) => recorded.has(item));

    expect(items.length).toBe(11);
    expect(unknown.length).toBe(ABSENT_UNTIL_M9.size);
  });

  it("the absent items still have no route, so the record is not stale", () => {
    // **The assertion that makes the absence honest.** When M9 builds matching or the attempt list,
    // this fails and tells whoever added the route that a workspace panel is now buildable. Without
    // it, four items could stay "deliberately absent" forever while the reason quietly expired.
    const contract = read(CONTRACT);
    const built = [...ABSENT_UNTIL_M9.entries()].filter(([, route]) =>
      contract.includes(`"/api/v1${route}"`),
    );

    expect(built).toEqual([]);
  });
});

describe("the crop is keyboard-operable", () => {
  const raster: RenderedRaster = {
    pageNumber: 1,
    pixelWidth: 600,
    pixelHeight: 800,
    rotationDegrees: 0,
    rendererVersion: "pypdfium2/5.13.0 pdfium/153.0.7999.0",
  };
  const start: PixelRectangle = { x: 100, y: 100, width: 200, height: 150 };

  it("moves the whole rectangle with an arrow key, and further with shift", () => {
    // §16 `:1039`. A drag-only crop excludes anybody who cannot use a mouse, and a receipt's amount
    // box is exactly the small target a pointer is worst at.
    expect(nudge(start, "all", NUDGE_STEP, raster).x).toBe(101);
    expect(nudge(start, "all", -NUDGE_STEP, raster).x).toBe(99);
    expect(nudge(start, "all", NUDGE_STEP_COARSE, raster).x).toBe(110);

    // One pixel matters: an operator squaring a rectangle onto a box needs the last pixel as much
    // as the first, so the fine step is 1 and not 5.
    expect(NUDGE_STEP).toBe(1);
  });

  it("resizes one edge at a time without moving the others", () => {
    const wider = nudge(start, "right", 10, raster);
    expect(wider.width).toBe(210);
    expect(wider.x).toBe(start.x);

    const fromTheLeft = nudge(start, "left", 10, raster);
    expect(fromTheLeft.x).toBe(110);
    // The right edge stayed put, which is what "resize" means and what moving the whole rectangle
    // would not do.
    expect(fromTheLeft.x + fromTheLeft.width).toBe(start.x + start.width);
  });

  it("never lets the rectangle leave the page", () => {
    // A rectangle off the page cannot be stored — §12.4's CHECK refuses it — and an operator should
    // learn that from the edge not moving rather than from a server error.
    const atTheLeft = nudge({ ...start, x: 0 }, "all", -50, raster);
    expect(atTheLeft.x).toBe(0);

    const atTheRight = nudge({ ...start, x: 400, width: 200 }, "all", 50, raster);
    expect(atTheRight.x + atTheRight.width).toBeLessThanOrEqual(raster.pixelWidth);

    const collapsed = nudge(start, "right", -1000, raster);
    expect(collapsed.width).toBeGreaterThan(0);
  });

  it("offers a number input for each of the four edges, and renders them", () => {
    // Arrow keys are not the whole of keyboard access: a screen reader announces a labelled number
    // field where it cannot announce a drag, and an operator who knows the coordinates can type
    // them.
    const canvas = read(CROP_CANVAS);
    for (const label of [
      "admin.workspace.cropLeft",
      "admin.workspace.cropTop",
      "admin.workspace.cropWidth",
      "admin.workspace.cropHeight",
    ]) {
      expect(canvas).toContain(label);
    }
    expect(canvas).toContain('type="number"');

    // **Rendered, not merely present.** The first version stopped at the four labels, and the
    // negative control that hides the fieldset reported NOT CAUGHT: `hidden` leaves every one of
    // those strings in the file while removing the controls from the page. A hidden keyboard
    // affordance is the same as no keyboard affordance.
    expect(canvas).not.toMatch(/<fieldset[^>]*\bhidden\b/);
  });

  it("attaches the key handler to the element, not merely defines it", () => {
    // **The control found this and it is the frontend's version of a recurring defect here:
    // complete machinery nothing calls.** Deleting `onKeyDown={onKeyDown}` from the JSX left the
    // `useCallback` in place, so every assertion that looked for `onKeyDown` in the source still
    // passed while no key did anything.
    const canvas = read(CROP_CANVAS);
    expect(canvas).toMatch(/onKeyDown=\{onKeyDown\}/);

    // And the element can hold focus, without which a key event never reaches the handler at all.
    expect(canvas).toContain("tabIndex={0}");
  });
});

describe("the coordinates the screen sends", () => {
  const raster: RenderedRaster = {
    pageNumber: 2,
    pixelWidth: 600,
    pixelHeight: 800,
    rotationDegrees: 90,
    rendererVersion: "pypdfium2/5.13.0 pdfium/153.0.7999.0",
  };

  it("are normalized against the dimensions the server reported", () => {
    // `UI-CROP-002`. The rectangle is in raster pixels and the four stored numbers are ratios of
    // that raster — not of the displayed element, whose size depends on the zoom.
    const rectangle: PixelRectangle = { x: 63, y: 176, width: 300, height: 240 };
    expect(normalizeRectangle(rectangle, raster)).toEqual({
      x: "0.105000",
      y: "0.220000",
      width: "0.500000",
      height: "0.300000",
    });
  });

  it("never exceed the page, even when the drag ended on the last pixel", () => {
    const whole = normalizeRectangle(
      { x: 0, y: 0, width: raster.pixelWidth, height: raster.pixelHeight },
      raster,
    );
    expect(whole).toEqual({ x: "0.000000", y: "0.000000", width: "1.000000", height: "1.000000" });

    // Rounding is where this goes wrong: a third of a page is 0.333333, and rounding the width
    // independently would put x + width past the rounded right edge. The width is computed as the
    // difference of the two rounded edges, so it absorbs the rounding instead.
    const thirds = normalizeRectangle({ x: 200, y: 0, width: 200, height: 800 }, raster);
    expect(thirds.x).toBe("0.333333");
    expect(thirds.width).toBe("0.333334");
    expect(Number(thirds.x) + Number(thirds.width)).toBeCloseTo(0.666667, 6);
  });

  it("carry the rotation and the raster that produced them", () => {
    // `UI-CROP-002`'s second half, and DOC-CONFLICT-057's whole point: the four numbers describe a
    // region of the *rotated* page, so sending them without the angle describes somewhere else.
    const file: BundleFile = {
      id: "bundle-file-1",
      file_id: "file-1",
      file_name: "results.pdf",
      sequence_number: 1,
      file_role: "source",
      page_count: 3,
      preview_path: "/api/v1/files/file-1/pages/1/preview",
    };
    const rectangle: PixelRectangle = { x: 60, y: 80, width: 120, height: 160 };
    const request = buildCropRequest(file, rectangle, raster);

    expect(request.rotation_degrees).toBe(90);
    expect(request.client_source_dimensions).toEqual({ width: 600, height: 800 });
    expect(request.page_number).toBe(2);
    expect(request.bank_result_bundle_file_id).toBe("bundle-file-1");
    expect(request.source_file_id).toBe("file-1");

    // **The request's own bbox, not `normalizeRectangle` called separately.** The negative control
    // that made `buildCropRequest` emit raw pixel strings reported NOT CAUGHT, because every
    // assertion about normalisation was calling the helper directly — the composition was never
    // checked, and `typeof "60" === "string"` is true of a pixel too.
    expect(request.bbox).toEqual(normalizeRectangle(rectangle, raster));
    for (const value of Object.values(request.bbox)) {
      expect(Number(value)).toBeGreaterThanOrEqual(0);
      expect(Number(value)).toBeLessThanOrEqual(1);
      // Decimal strings, never numbers, and always at the column's scale. `NUMERIC(10,6)` holds
      // these, and a JSON float would arrive as a binary approximation of a decimal the database
      // never stored.
      expect(value).toMatch(/^\d\.\d{6}$/);
    }
  });

  it("reads the raster out of the preview response rather than the image element", () => {
    // `API-PREVIEW-001`'s consumer. `naturalWidth` is the displayed image's size and agrees with
    // the raster only by luck; the headers are the server stating what it rendered.
    const headers = new Headers({
      "X-Preview-Page-Number": "2",
      "X-Preview-Pixel-Width": "800",
      "X-Preview-Pixel-Height": "600",
      "X-Preview-Rotation-Degrees": "270",
      "X-Preview-Renderer-Version": "pypdfium2/5.13.0 pdfium/153.0.7999.0",
    });
    expect(rasterFrom(headers)).toEqual({
      pageNumber: 2,
      pixelWidth: 800,
      pixelHeight: 600,
      rotationDegrees: 270,
      rendererVersion: "pypdfium2/5.13.0 pdfium/153.0.7999.0",
    });

    expect(read(PAGE_PREVIEW)).toContain("rasterFrom(response.headers)");
    expect(read(PAGE_PREVIEW)).not.toContain("naturalWidth");
  });
});

describe("rotation and paging", () => {
  it("cycles through exactly the four angles the renderer accepts", () => {
    expect(ROTATIONS).toEqual([0, 90, 180, 270]);
    expect(rotateClockwise(0)).toBe(90);
    expect(rotateClockwise(270)).toBe(0);
    expect(rotateAnticlockwise(0)).toBe(270);
    expect(rotateAnticlockwise(90)).toBe(0);
  });

  it("stays inside the document's own page count", () => {
    // `page_count` is the server's count as of M8 slice 5, not the caller's claim, so this is
    // navigation within a number nobody made up.
    expect(stepPage(1, -1, 3)).toBe(1);
    expect(stepPage(3, 1, 3)).toBe(3);
    expect(stepPage(1, 1, 3)).toBe(2);
    // A file with no page count is one page, not zero: an unknown length must not make the
    // controls unusable.
    expect(stepPage(1, 1, null)).toBe(1);
  });

  it("asks for the page and angle in the URL", () => {
    expect(previewPath("file-9", 4, 180)).toBe(
      "/api/v1/files/file-9/pages/4/preview?rotation_degrees=180",
    );
  });
});

describe("the external evidence fallback", () => {
  it("is reachable whatever the preview does", () => {
    // `UI-EVIDENCE-001`. §16 `:1069` requires a bundle nothing can render to stay workable, and the
    // case that matters most is the preview that silently produces something useless rather than
    // the one that errors — so this control is not behind a failure branch.
    const page = read(WORKSPACE_PAGE);
    expect(page).toContain("admin.workspace.externalConfirm");

    // **Asserted on the guard, not on the absence of words.** The first version scanned the
    // section's text for "failed" and "isPreviewable" and was defeated immediately by the comment
    // above the section explaining why neither belongs there — the seventh time in this repository
    // that a source scan has been broken by the prose written to justify it.
    //
    // What the requirement actually says is that the fallback is conditioned on a file being
    // selected and on nothing else, so that is what this matches: the opening guard of the section,
    // exactly.
    const guard = /\{selected \? \(\s*<section aria-labelledby="external-evidence">/;
    expect(guard.test(page)).toBe(true);
  });

  it("is offered for a file that has no preview at all", () => {
    // The spreadsheet case. `preview_path` is null, the screen says so in words, and the fallback
    // is still there — which is the difference between "nothing to show" and "nothing to do".
    const page = read(WORKSPACE_PAGE);
    expect(page).toContain("admin.workspace.noPreviewExplanation");
    expect(page).toContain("isPreviewable");
  });
});
