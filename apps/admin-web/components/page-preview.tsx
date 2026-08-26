"use client";

import { t } from "@gold/localization";
import { StateView } from "@gold/ui";
import { useEffect, useState } from "react";

import { CropCanvas } from "./crop-canvas";
import {
  type BundleFile,
  buildCropRequest,
  type CropRequest,
  type ManualFields,
  type PixelRectangle,
  previewPath,
  rasterFrom,
  type RenderedRaster,
  type Rotation,
} from "../src/bundles";

const INITIAL_RECTANGLE: PixelRectangle = { x: 20, y: 20, width: 120, height: 60 };

/**
 * One rendered page, and everything that is only true of that page.
 *
 * **A separate component so that a remount is the reset.** The raster, the image and the rectangle
 * are all measured against one page at one angle; when either changes they are not stale so much as
 * *about something else*. The page mounts this with a `key` of the file, page and rotation, so React
 * discards the old state instead of an effect clearing it — which is both simpler and what
 * `react-hooks/set-state-in-effect` is pointing at when it calls that a cascading render.
 *
 * The first version did clear it in an effect and the lint rule refused it. The rule was right for a
 * better reason than performance: a rectangle that survives a page change for even one render is a
 * rectangle drawn on a picture the operator is no longer looking at.
 */
export function PagePreview({
  bundleFile,
  pageNumber,
  rotation,
  fields,
  busy,
  onCrop,
}: {
  readonly bundleFile: BundleFile;
  readonly pageNumber: number;
  readonly rotation: Rotation;
  readonly fields: ManualFields;
  readonly busy: boolean;
  readonly onCrop: (request: CropRequest) => void;
}) {
  const [raster, setRaster] = useState<RenderedRaster | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [rectangle, setRectangle] = useState<PixelRectangle>(INITIAL_RECTANGLE);

  // **Fetched, not pointed at.** The `X-Preview-Pixel-*` headers are the only statement of the
  // raster the server actually rendered, and a coordinate normalised against anything else — a
  // natural width, a bounding box — is a coordinate the crop route refuses. An `<img src>` would
  // show the picture and throw the headers away.
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;

    void fetch(previewPath(bundleFile.file_id, pageNumber, rotation), {
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        const measured = rasterFrom(response.headers);
        objectUrl = URL.createObjectURL(await response.blob());
        setRaster(measured);
        setImageUrl(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [bundleFile.file_id, pageNumber, rotation]);

  if (failed) {
    return (
      <StateView
        description={t("admin.workspace.failed")}
        headingLevel={3}
        kind="error"
        title={t("admin.workspace.failedTitle")}
      />
    );
  }

  if (!raster || !imageUrl) {
    return (
      <StateView
        description={t("admin.workspace.loading")}
        headingLevel={3}
        kind="loading"
        title={t("admin.workspace.loading")}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <CropCanvas
        imageUrl={imageUrl}
        onRectangleChange={setRectangle}
        raster={raster}
        rectangle={rectangle}
      />
      <button
        className="self-start rounded-lg bg-[var(--accent)] px-4 py-2 font-bold text-[var(--on-accent)] disabled:opacity-60"
        disabled={busy}
        onClick={() => onCrop(buildCropRequest(bundleFile, rectangle, raster, fields))}
        type="button"
      >
        {t("admin.workspace.createCrop")}
      </button>
    </div>
  );
}
