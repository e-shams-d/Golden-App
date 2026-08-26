"use client";

import { t, toPersianDigits } from "@gold/localization";
import { useCallback, useRef, useState } from "react";

import {
  CROP_MIN_PIXELS,
  NUDGE_STEP,
  NUDGE_STEP_COARSE,
  normalizeRectangle,
  nudge,
  type PixelRectangle,
  type RenderedRaster,
} from "../src/bundles";

/**
 * The page image and the rectangle drawn on it. §16.3's crop selection and keyboard controls.
 *
 * **The rectangle lives in the raster's pixels, never in the screen's.** An operator dragging at
 * 150% zoom moves twice as many screen pixels as raster pixels, and the four numbers the server
 * stores are ratios of the *raster*. So every pointer event is divided by the zoom before it
 * becomes a coordinate, and the rectangle is drawn back out multiplied by it. Getting that backwards
 * produces a crop that is refused by the server's `client_source_dimensions` check — which is the
 * safe failure, and still a screen that cannot work.
 *
 * **Zoom and pan are here and go no further.** They change which pixels a person is looking at and
 * nothing about which pixels get cut, so no zoom factor is ever sent with a crop.
 *
 * **Every pointer gesture has a keyboard equivalent, and the keyboard is not the fallback.** §16
 * `:1039` requires keyboard-accessible controls, and a receipt's amount box is exactly the small
 * target a pointer is worst at. The four edges each have a number input, and arrow keys move the
 * whole rectangle — `Shift` by ten pixels, `Alt` resizing the edge in that direction instead.
 */
export function CropCanvas({
  imageUrl,
  raster,
  rectangle,
  onRectangleChange,
}: {
  readonly imageUrl: string;
  readonly raster: RenderedRaster;
  readonly rectangle: PixelRectangle;
  readonly onRectangleChange: (next: PixelRectangle) => void;
}) {
  // Reset by remount, not by an effect. `PagePreview` mounts this with a key of the file, page and
  // rotation, so a new raster is a new component and every piece of state here starts fresh — the
  // zoom included. An effect calling `setZoom(1)` was the first version, and
  // `react-hooks/set-state-in-effect` refused it for a better reason than performance: a rectangle
  // that survives a page change for even one render is drawn on a picture nobody is looking at.
  const [zoom, setZoom] = useState(1);
  const surface = useRef<HTMLDivElement>(null);
  const dragOrigin = useRef<{ x: number; y: number } | null>(null);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const step = event.shiftKey ? NUDGE_STEP_COARSE : NUDGE_STEP;
      const resizing = event.altKey;

      const move = (edge: "left" | "right" | "top" | "bottom" | "all", delta: number) => {
        event.preventDefault();
        onRectangleChange(nudge(rectangle, edge, delta, raster));
      };

      // Left and right are physical directions on a rendered image, not reading directions. The
      // surrounding page is RTL and this element is not text: an operator pressing the left arrow
      // means the left of the picture, and mirroring it here would make the rectangle move away
      // from the pointer.
      if (event.key === "ArrowLeft") move(resizing ? "right" : "all", -step);
      else if (event.key === "ArrowRight") move(resizing ? "right" : "all", step);
      else if (event.key === "ArrowUp") move(resizing ? "bottom" : "all", -step);
      else if (event.key === "ArrowDown") move(resizing ? "bottom" : "all", step);
    },
    [onRectangleChange, raster, rectangle],
  );

  const pointerPosition = (event: React.PointerEvent): { x: number; y: number } | null => {
    const box = surface.current?.getBoundingClientRect();
    if (!box) return null;
    // Divided by the zoom, which is the whole reason this function exists rather than using the
    // offsets directly: `offsetX` is in screen pixels and every coordinate below is in raster ones.
    return {
      x: Math.round((event.clientX - box.left) / zoom),
      y: Math.round((event.clientY - box.top) / zoom),
    };
  };

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    const at = pointerPosition(event);
    if (!at) return;
    dragOrigin.current = at;
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const origin = dragOrigin.current;
    const at = pointerPosition(event);
    if (!origin || !at) return;

    const x = Math.max(0, Math.min(origin.x, at.x));
    const y = Math.max(0, Math.min(origin.y, at.y));
    const width = Math.min(raster.pixelWidth - x, Math.abs(at.x - origin.x));
    const height = Math.min(raster.pixelHeight - y, Math.abs(at.y - origin.y));
    if (width < CROP_MIN_PIXELS || height < CROP_MIN_PIXELS) return;

    onRectangleChange({ x, y, width, height });
  };

  const onPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    dragOrigin.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const normalized = normalizeRectangle(rectangle, raster);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          className="rounded-lg border border-[var(--border)] px-3 py-1 font-bold"
          onClick={() => setZoom((current) => Math.min(4, current + 0.25))}
          type="button"
        >
          {t("admin.workspace.zoomIn")}
        </button>
        <button
          className="rounded-lg border border-[var(--border)] px-3 py-1 font-bold"
          onClick={() => setZoom((current) => Math.max(0.25, current - 0.25))}
          type="button"
        >
          {t("admin.workspace.zoomOut")}
        </button>
        <button
          className="rounded-lg border border-[var(--border)] px-3 py-1 font-bold"
          onClick={() => setZoom(1)}
          type="button"
        >
          {t("admin.workspace.zoomReset")}
        </button>
        <span className="text-sm text-[var(--muted)]">
          {t("admin.workspace.zoomLevel")}: {toPersianDigits(String(Math.round(zoom * 100)))}٪
        </span>
      </div>

      {/* `overflow-auto` is the pan: the surface is larger than its frame at any zoom above 1, and
          scrolling it is what moves the view. A bespoke drag-to-pan would take the pointer away
          from the crop, which is the gesture this element is actually for. */}
      <div className="max-h-[32rem] overflow-auto rounded-2xl border border-[var(--border)] bg-[var(--surface-sunken)] p-2">
        <div
          aria-label={t("admin.workspace.crop")}
          className="relative touch-none select-none"
          onKeyDown={onKeyDown}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          ref={surface}
          role="application"
          style={{
            width: raster.pixelWidth * zoom,
            height: raster.pixelHeight * zoom,
          }}
          tabIndex={0}
        >
          {/* Not `next/image`: the source is an authenticated same-origin API response whose size is
              known only at runtime, and the optimizer would proxy it through a loader that does not
              carry the session. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt={`${t("admin.workspace.page")} ${toPersianDigits(String(raster.pageNumber))}`}
            className="pointer-events-none absolute inset-0 h-full w-full"
            src={imageUrl}
          />
          <div
            aria-hidden="true"
            className="absolute border-2 border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_18%,transparent)]"
            style={{
              left: rectangle.x * zoom,
              top: rectangle.y * zoom,
              width: rectangle.width * zoom,
              height: rectangle.height * zoom,
            }}
          />
        </div>
      </div>

      <p className="text-sm text-[var(--muted)]">{t("admin.workspace.cropHint")}</p>

      {/* The keyboard half of §16 `:1039`, and the reason it is number inputs rather than only arrow
          keys: an operator who knows the coordinates can type them, and a screen reader announces a
          labelled number field where it cannot announce a drag. */}
      <fieldset className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <legend className="sr-only">{t("admin.workspace.crop")}</legend>
        <NumberField
          label={t("admin.workspace.cropLeft")}
          max={raster.pixelWidth - CROP_MIN_PIXELS}
          onChange={(value) => onRectangleChange({ ...rectangle, x: value })}
          value={rectangle.x}
        />
        <NumberField
          label={t("admin.workspace.cropTop")}
          max={raster.pixelHeight - CROP_MIN_PIXELS}
          onChange={(value) => onRectangleChange({ ...rectangle, y: value })}
          value={rectangle.y}
        />
        <NumberField
          label={t("admin.workspace.cropWidth")}
          max={raster.pixelWidth - rectangle.x}
          onChange={(value) => onRectangleChange({ ...rectangle, width: value })}
          value={rectangle.width}
        />
        <NumberField
          label={t("admin.workspace.cropHeight")}
          max={raster.pixelHeight - rectangle.y}
          onChange={(value) => onRectangleChange({ ...rectangle, height: value })}
          value={rectangle.height}
        />
      </fieldset>

      {/* Shown, not hidden: these four numbers are what gets stored, and an operator who can see
          them can tell a mis-drawn rectangle from a mis-rendered page. */}
      <dl className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4" data-testid="normalized">
        <Coordinate label="x" value={normalized.x} />
        <Coordinate label="y" value={normalized.y} />
        <Coordinate label="width" value={normalized.width} />
        <Coordinate label="height" value={normalized.height} />
      </dl>
      <p className="text-sm text-[var(--muted)]">{t("admin.workspace.normalizedExplanation")}</p>
      <p className="text-sm text-[var(--muted)]">
        {t("admin.workspace.rasterSize")}: {toPersianDigits(String(raster.pixelWidth))}×
        {toPersianDigits(String(raster.pixelHeight))}
      </p>
    </div>
  );
}

function NumberField({
  label,
  value,
  max,
  onChange,
}: {
  readonly label: string;
  readonly value: number;
  readonly max: number;
  readonly onChange: (value: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm font-bold">
      {label}
      <input
        className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
        max={max}
        min={0}
        onChange={(event) => {
          const parsed = Number(event.target.value);
          if (Number.isFinite(parsed)) onChange(Math.max(0, Math.min(max, Math.round(parsed))));
        }}
        type="number"
        value={value}
      />
    </label>
  );
}

function Coordinate({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="rounded-lg bg-[var(--surface-sunken)] px-3 py-2">
      <dt className="text-[var(--muted)]">{label}</dt>
      {/* Latin digits deliberately. This is the exact string sent to the server and stored in
          `NUMERIC(10,6)`; rendering it in Persian digits would show a value that is not the one on
          the wire, in the one place where an operator might be checking exactly that. */}
      <dd className="font-mono">{value}</dd>
    </div>
  );
}
