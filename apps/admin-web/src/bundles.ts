/**
 * The bank-result review workspace, as the screen sees it. §16.3 of the implementation plan.
 *
 * M8 slice 6. Per-app for `src/batches.ts`'s reason: `UI-ISO-001` requires that neither bundle
 * contain the other's endpoint paths, and a bank-result bundle has no trader-side counterpart at
 * all — doc 05 `:1045` says in terms that a trader cannot preview an internal mixed bundle.
 *
 * **Everything a crop depends on is computed here, and none of it is measured from the DOM.** The
 * rectangle an operator drags is in screen pixels of a rendered image; what the server stores is
 * four decimals normalised against *the raster it rendered*. Those are only the same thing if the
 * image is displayed at its natural size, which it never is once zoom exists. So the raster comes
 * from the preview response's own `X-Preview-Pixel-*` headers and the screen divides by that —
 * never by `naturalWidth`, never by a bounding rectangle.
 *
 * The server refuses a mismatch (`client_source_dimensions` against its own render), so getting
 * this wrong does not produce a wrong crop; it produces a crop that is always rejected. That is the
 * better failure, and it is why the check exists — but it is still a screen that cannot work, and
 * this module is where it is made to.
 *
 * **Zoom and pan never leave the browser.** They change which pixels a person is looking at and
 * nothing about which pixels the server cut. A zoom factor sent with a crop would be a number the
 * server has no use for and a reader would assume mattered.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** One file inside a bundle, as slice 1 and slice 5 return it. */
export type BundleFile = Readonly<{
  id: string;
  file_id: string;
  file_name: string;
  sequence_number: number;
  file_role: string;
  page_count: number | null;
  /** `null` when there is nothing to render — an Excel result, a CSV. */
  preview_path: string | null;
}>;

/** One row of the queue. `05_API_Specification.md:1676`. */
export type BundleSummary = Readonly<{
  id: string;
  bundle_number: string;
  status: string;
  source_type: string;
  bank: string | null;
  uploaded_by: string | null;
  uploaded_at: string;
  file_count: number;
  segment_count: number;
  resolved_segment_count: number;
  unresolved_segment_count: number;
  record_version: number;
}>;

/**
 * Which batch this bundle appears to answer.
 *
 * **`proves_payment` is a field and is always `false`.** `05_API_Specification.md:1688` calls the
 * association "operational context only" — a screen that put a batch number beside a bundle would
 * be read as a claim about payment unless something contradicted it, and the server contradicts it
 * in the payload rather than leaving it to a caption.
 *
 * `link_method` records **how** the link was made: a person choosing, a reference on the export, or
 * a note. `replaced_at` is set when a later link supersedes this one — the row stays, so how a
 * bundle came to be attached to a batch is answerable after somebody changed their mind.
 */
export type BatchLink = Readonly<{
  id: string;
  payment_batch_id: string;
  batch_number: string;
  payment_batch_version_id: string | null;
  link_method: string;
  status: string;
  created_by: string | null;
  created_at: string;
  replaced_at: string | null;
  proves_payment: boolean;
}>;

/** `05_API_Specification.md:1680`'s detail response. */
export type BundleDetail = Readonly<{
  id: string;
  bundle_number: string;
  status: string;
  source_type: string;
  segment_count: number;
  resolved_segment_count: number;
  unresolved_segment_count: number;
  notes: string | null;
  files: readonly BundleFile[];
  batch_links: readonly BatchLink[];
  /**
   * The vocabulary the server accepts, **read rather than copied**.
   *
   * `bank_result_bundle.py` sends these so a client does not hold its own list — one that would
   * disagree the day the server gains a value, and disagree silently.
   */
  accepted_link_methods: readonly string[];
  record_version: number;
}>;

/** The raster the server actually rendered, read from the preview response's headers. */
export type RenderedRaster = Readonly<{
  pageNumber: number;
  pixelWidth: number;
  pixelHeight: number;
  rotationDegrees: number;
  rendererVersion: string;
}>;

/** A rectangle in the rendered image's own pixels, which is what a drag produces. */
export type PixelRectangle = Readonly<{
  x: number;
  y: number;
  width: number;
  height: number;
}>;

/** The four decimal strings `receipt_segments` stores. */
export type NormalizedRectangle = Readonly<{
  x: string;
  y: string;
  width: string;
  height: string;
}>;

/**
 * The four angles doc 08 `:985`'s control can produce, in clockwise order.
 *
 * A tuple rather than arithmetic, because `(current + 90) % 360` silently admits any starting value
 * — including one that arrived from a query string — and the server's CHECK would then refuse a
 * crop for a reason the screen could have prevented.
 */
export const ROTATIONS = [0, 90, 180, 270] as const;

export type Rotation = (typeof ROTATIONS)[number];

/** `NUMERIC(10,6)`, so six decimal places and no more. */
const SCALE = 6;

/**
 * How far an arrow key moves an edge, in pixels of the rendered raster.
 *
 * One pixel, and `Shift` multiplies it. §16 `:1039` requires keyboard-accessible controls, and a
 * keyboard crop that could only move in ten-pixel jumps would be accessible in name: an operator
 * squaring a rectangle onto a receipt's amount box needs the last pixel as much as the first.
 */
export const NUDGE_STEP = 1;
export const NUDGE_STEP_COARSE = 10;

export const CROP_MIN_PIXELS = 2;

/**
 * Normalise a dragged rectangle against the raster the server reported.
 *
 * **Rounded to six places and then clamped**, in that order, because rounding can push a rectangle
 * that ended exactly on the right edge past 1.0 — and `x + width > 1` is refused by both the
 * renderer and §12.4's CHECK. An operator who dragged to the edge of the page means the edge of the
 * page; failing their crop over a rounding artefact would be the screen's fault and would look like
 * the server's.
 */
export function normalizeRectangle(
  rectangle: PixelRectangle,
  raster: RenderedRaster,
): NormalizedRectangle {
  if (raster.pixelWidth <= 0 || raster.pixelHeight <= 0) {
    throw new Error("the rendered raster has no size; a rectangle cannot be normalised against it");
  }

  const left = clamp01(rectangle.x / raster.pixelWidth);
  const top = clamp01(rectangle.y / raster.pixelHeight);
  const right = clamp01((rectangle.x + rectangle.width) / raster.pixelWidth);
  const bottom = clamp01((rectangle.y + rectangle.height) / raster.pixelHeight);

  const x = left.toFixed(SCALE);
  const y = top.toFixed(SCALE);
  return {
    x,
    y,
    width: subtract(right.toFixed(SCALE), x),
    height: subtract(bottom.toFixed(SCALE), y),
  };
}

/**
 * Subtract two six-place decimal strings without going through a float.
 *
 * `0.83 - 0.166` in IEEE arithmetic is `0.6639999999999999`, and `0.3 - 0.1` is
 * `0.19999999999999998` — both from ratios a 600-pixel-wide raster produces readily. `toFixed(6)`
 * would paper over each, but the unrounded value is what carries into the next calculation.
 * Working in integer millionths keeps exactly the value the database will hold: the same reasoning
 * `MONEY_TIME_CONTRACT.md` applies to money, applied to the other kind of value in this system
 * where the exact digits are the point.
 *
 * (Measured, not assumed. The pair first written in this comment — `0.79 - 0.105` — turned out to
 * be exact in IEEE, so the claim was replaced with two that are not.)
 */
function subtract(minuend: string, subtrahend: string): string {
  const difference = millionths(minuend) - millionths(subtrahend);
  return fromMillionths(difference);
}

function millionths(value: string): number {
  const [whole, fraction = ""] = value.split(".");
  return Number(whole) * 1_000_000 + Number(fraction.padEnd(SCALE, "0").slice(0, SCALE));
}

function fromMillionths(value: number): string {
  const whole = Math.trunc(value / 1_000_000);
  const fraction = Math.abs(value % 1_000_000);
  return `${whole}.${String(fraction).padStart(SCALE, "0")}`;
}

function clamp01(value: number): number {
  if (Number.isNaN(value)) {
    return 0;
  }
  return Math.min(1, Math.max(0, value));
}

/**
 * Move or resize a rectangle with the keyboard. §16 `:1039`.
 *
 * **The whole reason this exists**: a crop that can only be dragged excludes anybody who cannot use
 * a mouse, and a receipt's amount box is exactly the kind of small target a pointer is worst at. The
 * four edges move independently, so an operator can square a rectangle onto a box without ever
 * touching a pointing device.
 *
 * Bounded by the raster on every side, because a rectangle that left the page could not be stored
 * and the operator would learn that from a server error rather than from the edge not moving.
 */
export function nudge(
  rectangle: PixelRectangle,
  edge: "left" | "right" | "top" | "bottom" | "all",
  delta: number,
  raster: RenderedRaster,
): PixelRectangle {
  const maxX = raster.pixelWidth;
  const maxY = raster.pixelHeight;

  if (edge === "all") {
    const x = clamp(rectangle.x + delta, 0, maxX - rectangle.width);
    const y = clamp(rectangle.y + delta, 0, maxY - rectangle.height);
    return { ...rectangle, x, y };
  }

  if (edge === "left") {
    const x = clamp(rectangle.x + delta, 0, rectangle.x + rectangle.width - CROP_MIN_PIXELS);
    return { ...rectangle, x, width: rectangle.x + rectangle.width - x };
  }
  if (edge === "right") {
    const right = clamp(rectangle.x + rectangle.width + delta, rectangle.x + CROP_MIN_PIXELS, maxX);
    return { ...rectangle, width: right - rectangle.x };
  }
  if (edge === "top") {
    const y = clamp(rectangle.y + delta, 0, rectangle.y + rectangle.height - CROP_MIN_PIXELS);
    return { ...rectangle, y, height: rectangle.y + rectangle.height - y };
  }
  const bottom = clamp(rectangle.y + rectangle.height + delta, rectangle.y + CROP_MIN_PIXELS, maxY);
  return { ...rectangle, height: bottom - rectangle.y };
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/**
 * The next angle clockwise, doc 08 `:985`'s control.
 *
 * `?? 0` rather than a non-null assertion: the index is always in range, and under
 * `noUncheckedIndexedAccess` saying so with `!` asserts a fact the compiler cannot check while this
 * says what happens if it were ever wrong — an unrotated page, which is the safe answer.
 */
export function rotateClockwise(current: Rotation): Rotation {
  return ROTATIONS[(ROTATIONS.indexOf(current) + 1) % ROTATIONS.length] ?? 0;
}

/** And the other way, which the same line of the document requires. */
export function rotateAnticlockwise(current: Rotation): Rotation {
  return ROTATIONS[(ROTATIONS.indexOf(current) + ROTATIONS.length - 1) % ROTATIONS.length] ?? 0;
}

/**
 * Which page to show next, bounded by what the file actually has.
 *
 * `page_count` is the server's count of the document — slice 5 stopped it being the caller's claim —
 * so this is navigation within a number nobody made up.
 */
export function stepPage(current: number, delta: number, pageCount: number | null): number {
  const last = pageCount && pageCount > 0 ? pageCount : 1;
  return clamp(current + delta, 1, last);
}

/** The preview URL for one page at one angle. Built here so no component assembles a path. */
export function previewPath(fileId: string, pageNumber: number, rotation: Rotation): string {
  return `/api/v1/files/${fileId}/pages/${pageNumber}/preview?rotation_degrees=${rotation}`;
}

/** Read the raster the server rendered out of its response. `API-PREVIEW-001`'s consumer. */
export function rasterFrom(headers: Headers): RenderedRaster {
  const number = (name: string): number => Number(headers.get(name) ?? "0");
  return {
    pageNumber: number("X-Preview-Page-Number"),
    pixelWidth: number("X-Preview-Pixel-Width"),
    pixelHeight: number("X-Preview-Pixel-Height"),
    rotationDegrees: number("X-Preview-Rotation-Degrees"),
    rendererVersion: headers.get("X-Preview-Renderer-Version") ?? "",
  };
}

export type ManualFields = Readonly<{
  beneficiary_name?: string;
  destination_iban?: string;
  /** A string on the wire. An IRR amount can exceed `Number.MAX_SAFE_INTEGER`. */
  amount_irr?: string;
  tracking_number?: string;
}>;

export type CropRequest = Readonly<{
  bank_result_bundle_file_id: string;
  source_file_id: string;
  page_number: number;
  bbox: NormalizedRectangle;
  client_source_dimensions: Readonly<{ width: number; height: number }>;
  rotation_degrees: number;
  manual_fields?: ManualFields;
}>;

/**
 * Build the crop request from what is on screen. `UI-CROP-002`.
 *
 * **The dimensions and the rotation come from the same `RenderedRaster` the rectangle was
 * normalised against**, and that is the whole point of passing one object rather than three
 * numbers: coordinates from one render and dimensions from another describe a region nobody
 * selected, and every field here has to belong to a single image.
 */
export function buildCropRequest(
  file: BundleFile,
  rectangle: PixelRectangle,
  raster: RenderedRaster,
  fields?: ManualFields,
): CropRequest {
  return {
    bank_result_bundle_file_id: file.id,
    source_file_id: file.file_id,
    page_number: raster.pageNumber,
    bbox: normalizeRectangle(rectangle, raster),
    client_source_dimensions: { width: raster.pixelWidth, height: raster.pixelHeight },
    rotation_degrees: raster.rotationDegrees,
    ...(fields ? { manual_fields: fields } : {}),
  };
}

export async function createCrop(bundleId: string, request: CropRequest): Promise<unknown> {
  const response = await transport.request<unknown, CropRequest>({
    method: "POST",
    path: `/bank-result-bundles/${encodeURIComponent(bundleId)}/receipt-segments/crop`,
    body: request,
    // `command_catalog.yaml:277` says `idempotency: required`. Generated per call rather than per
    // rectangle: a retried *request* must not produce a second segment, and two crops of the same
    // region are two deliberate acts if a person made them twice.
    idempotencyKey: crypto.randomUUID(),
  });
  return response.data;
}

/**
 * §16 `:1040`'s external evidence fallback. `UI-EVIDENCE-001`.
 *
 * **Kept reachable whatever the preview does**, which is the requirement rather than a convenience:
 * §16 `:1069` asks that a bundle nothing can render still be workable, and the file that cannot be
 * rendered is exactly the one where an operator needs to attach the whole thing as evidence. A
 * screen that only offered this when a preview failed would hide it in the case where the preview
 * silently produced something useless.
 */
export async function attachExternalEvidence(
  bundleId: string,
  sourceFileId: string,
  bundleFileId: string | null,
  fields?: ManualFields,
): Promise<unknown> {
  const response = await transport.request<unknown>({
    method: "POST",
    path: `/bank-result-bundles/${encodeURIComponent(bundleId)}/receipt-segments/external`,
    body: {
      source_file_id: sourceFileId,
      bank_result_bundle_file_id: bundleFileId,
      ...(fields ? { manual_fields: fields } : {}),
    },
    idempotencyKey: crypto.randomUUID(),
  });
  return response.data;
}

/**
 * The queue of bundles waiting to be looked at.
 *
 * **The workspace's only way in.** A detail screen with no list is one reachable by typing a URL,
 * which `UI-REQ-004` refuses — and it refuses it for an operational reason rather than a tidiness
 * one: nobody memorises a bundle id, so a workspace without a queue is a workspace nobody opens.
 */
export async function listBundles(signal?: AbortSignal): Promise<readonly BundleSummary[]> {
  // A bare array, not a paginated envelope: slice 1's route is `response_model=list[BundleSummary]`.
  // Written after checking the route rather than assuming the shape every other list here uses —
  // an `items` that does not exist would have been a runtime error the type system waves through.
  const response = await transport.request<readonly BundleSummary[]>({
    method: "GET",
    path: "/bank-result-bundles",
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * Bundles with work left in them, worst first.
 *
 * Sorted by unresolved count rather than by date, because §16.3's first item is "bundle summary and
 * **unresolved navigation**": the question an operator opens this screen with is "what still needs
 * me", not "what arrived most recently".
 */
export function byOutstandingWork(
  bundles: readonly BundleSummary[],
): readonly BundleSummary[] {
  return [...bundles].sort((left, right) => {
    if (left.unresolved_segment_count !== right.unresolved_segment_count) {
      return right.unresolved_segment_count - left.unresolved_segment_count;
    }
    // Older first among equals: a bundle that has waited longer is the one to look at.
    return left.uploaded_at.localeCompare(right.uploaded_at);
  });
}

export async function readBundle(bundleId: string, signal?: AbortSignal): Promise<BundleDetail> {
  const response = await transport.request<BundleDetail>({
    method: "GET",
    path: `/bank-result-bundles/${encodeURIComponent(bundleId)}`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * One cut of a bank result, and what the platform read out of it.
 *
 * M0 slice E. The four `extracted_*` fields are what a person matches against — the amount and the
 * tracking number above all, which is the same pair `app/statements/parser.py` makes its
 * `REQUIRED_FIELDS`. `null` in any of them means the platform could not read it, not that the
 * receipt lacked it: §8.4 requires an unparseable field to be left null rather than guessed.
 */
export type SegmentSummary = Readonly<{
  id: string;
  status: string;
  creation_method: string;
  page_number: number | null;
  segment_file_id: string | null;
  extracted_amount_irr: string | null;
  extracted_tracking_number: string | null;
  extracted_beneficiary_name: string | null;
  privacy_verified: boolean;
  record_version: number;
  created_at: string;
}>;

/** A suggestion. **Advisory** — `05_API_Specification.md:1802` says so in terms. */
export type MatchingCandidate = Readonly<{
  id: string;
  receipt_segment_id: string;
  payment_attempt_id: string;
  method: string;
  score: string | null;
  reasons: readonly string[];
  status: string;
  created_at: string;
  resolved_at: string | null;
}>;

export async function listSegments(
  bundleId: string,
  signal?: AbortSignal,
): Promise<readonly SegmentSummary[]> {
  const response = await transport.request<readonly SegmentSummary[]>({
    method: "GET",
    path: `/bank-result-bundles/${encodeURIComponent(bundleId)}/receipt-segments`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

export async function listCandidates(
  segmentId: string,
  signal?: AbortSignal,
): Promise<readonly MatchingCandidate[]> {
  const response = await transport.request<readonly MatchingCandidate[]>({
    method: "GET",
    path: `/receipt-segments/${encodeURIComponent(segmentId)}/matching-candidates`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * Suggest that this segment is evidence for an attempt.
 *
 * **No `method` and no `score`.** The route defaults `method` to `manual`, and a score sent from
 * here would be a human guess wearing the shape of something computed — `ProposeRequest`'s own
 * docstring refuses a default of 1.0 for exactly that reason. When an engine proposes, it will
 * send both, and the unique on `(segment, attempt, method)` is what lets it suggest the same pair a
 * person already did without colliding.
 */
export async function proposeCandidate(
  segmentId: string,
  paymentAttemptId: string,
): Promise<MatchingCandidate> {
  const response = await transport.request<MatchingCandidate, Record<string, unknown>>({
    method: "POST",
    path: `/receipt-segments/${encodeURIComponent(segmentId)}/matching-candidates`,
    body: { payment_attempt_id: paymentAttemptId },
    // Load bearing rather than decorative: without it a retried request is refused by
    // `uq_candidate_segment_attempt_method`, which tells the operator somebody else proposed this
    // link when in fact they did it themselves.
    idempotencyKey: crypto.randomUUID(),
  });
  return response.data;
}

/**
 * Accept a suggestion. **This marks nothing paid**, and the screen says so where it is clicked.
 *
 * `05_API_Specification.md:1810` states the prohibition, `:1274` repeats it and
 * `command_catalog.yaml:296` carries it as a precondition. What acceptance opens is the
 * confirmation context; what closes it is `confirm-paid`, which needs a tracking number, a result
 * timestamp and a person — none of which a candidate carries.
 */
export async function acceptCandidate(
  candidateId: string,
  reason?: string,
): Promise<MatchingCandidate> {
  const response = await transport.request<MatchingCandidate, Record<string, unknown>>({
    method: "POST",
    path: `/matching-candidates/${encodeURIComponent(candidateId)}/accept-for-confirmation`,
    body: { reason: reason?.trim() ? reason : null },
    idempotencyKey: crypto.randomUUID(),
  });
  return response.data;
}

/**
 * Refuse a suggestion, **always with a reason**.
 *
 * The command requires one where `:1820` asks for it only "when rejecting a high-confidence
 * candidate or overriding a previously accepted candidate" — the second case is exact and the first
 * has no approved threshold, so the server refuses "sometimes" rather than inventing the boundary.
 * The screen collects one for every rejection because that is what the server will accept.
 */
export async function rejectCandidate(
  candidateId: string,
  reason: string,
): Promise<MatchingCandidate> {
  const response = await transport.request<MatchingCandidate, Record<string, unknown>>({
    method: "POST",
    path: `/matching-candidates/${encodeURIComponent(candidateId)}/reject`,
    body: { reason },
    idempotencyKey: crypto.randomUUID(),
  });
  return response.data;
}

/**
 * The batch number an accountant chooses from, and the one thing this list must not become.
 *
 * **The owner's decision of 2026-09-13**: a person picks the batch by its number rather than the
 * platform deciding from a file name. Their first instinct was the safe half of it — "the
 * accountant should know which batch this is for" — and the unsafe half was recognising it from
 * the file's name with an instruction not to rename. A name leaves this building: the bank renames
 * it, a mail client renames it, a download adds `(1)`, and an instruction is what gets skipped on a
 * busy day. A bundle attached to the wrong batch is invisible; one attached to nothing is not.
 *
 * So the file name may be shown as a hint and never decides. `link_method: "manual_selection"` is
 * what the server then records, and a later reader can tell a person's choice from a guess.
 */
export type BatchChoice = Readonly<{
  id: string;
  batch_number: string;
  status: string;
  row_count: number;
  /** A base-10 integer string. `MONEY_TIME_CONTRACT.md` rule 9 keeps it out of `Number`. */
  total_amount_irr: string;
  version_created_at: string | null;
}>;

/**
 * Every batch, for the picker.
 *
 * **`{ batches: [...] }`, and no `limit`.** Written after reading the contract rather than assuming
 * the `{ items, next_cursor }` shape three other lists in this application use: `GET
 * /payment-batches` answers a bare envelope and takes one query parameter, `awaiting_decision`. A
 * guessed shape would have been a runtime error the type system waved through, and a guessed
 * `limit` would have been refused as an undeclared parameter.
 */
/**
 * A batch number as it appears inside a file name, or `null`.
 *
 * **Deliberately strict**: the full `PB-YYYYMMDD-NNNNNN` shape, anchored to word boundaries. A
 * looser pattern would match a bare date in a file name and pre-select a batch at random — worse
 * than matching nothing, because the operator would then be confirming a suggestion instead of
 * making a choice.
 *
 * Here rather than in the component that shows it, so it can be tested as what it is: a pure
 * function over a string, with the names that actually arrive — renamed by a mail client, suffixed
 * by a download, appended to by the bank.
 *
 * **The boundaries are explicit rather than `\b`, and a test is why.** `\b` after the digits fails
 * on `PB-20260913-000001_bank_final.xlsx`, because `_` is a word character and there is no boundary
 * between `1` and `_` — which is exactly the rename a bank produces. The leading guard refuses a
 * number glued to other text, and the trailing one refuses a longer digit run, so
 * `PB-20260913-0000012` matches nothing rather than matching a different batch.
 */
export function batchNumberInFileName(fileName: string): string | null {
  const found = /(?<![0-9A-Za-z])PB-\d{8}-\d{6}(?!\d)/.exec(fileName);
  return found ? found[0] : null;
}

export async function listBatchesForLinking(
  signal?: AbortSignal,
): Promise<readonly BatchChoice[]> {
  const response = await transport.request<{ batches: readonly BatchChoice[] }>({
    method: "GET",
    path: "/payment-batches",
    ...(signal ? { signal } : {}),
  });
  return response.data.batches;
}

/**
 * Record that this bundle appears to answer that batch.
 *
 * **Not evidence of payment**, and the route's own summary says so. A repeat call supersedes the
 * previous link rather than deleting it — `uq_bundle_links_active_pair` keeps one active pair and
 * the old row stays with a `replaced_at`, so changing your mind is recorded rather than erased.
 *
 * **No `Idempotency-Key`, and that is checked rather than assumed.** `command_catalog.yaml` has no
 * row for this command, so there is no idempotency contract to honour, and the unique makes a
 * repeat harmless. The route accepts no such header; sending one would be this screen inventing a
 * control.
 */
export async function linkBundleToBatch(
  bundleId: string,
  paymentBatchId: string,
  linkMethod: string,
): Promise<BatchLink> {
  const response = await transport.request<BatchLink, Record<string, unknown>>({
    method: "POST",
    path: `/bank-result-bundles/${encodeURIComponent(bundleId)}/batch-links`,
    body: { payment_batch_id: paymentBatchId, link_method: linkMethod },
  });
  return response.data;
}

/**
 * Whether this file can be previewed at all, and the reason a workspace needs to know.
 *
 * Read from `preview_path` rather than guessed from a name or a media type: slice 5 made the server
 * decide it once, at attach, with the bytes in hand. A screen re-deciding would eventually disagree
 * — and the disagreement would show as an operator being offered a preview that 400s.
 */
export function isPreviewable(file: BundleFile): boolean {
  return file.preview_path !== null;
}
