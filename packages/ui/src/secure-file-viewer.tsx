"use client";

import { useEffect, useState } from "react";

/**
 * `21_UI_Design_System_and_Screen_Specification.md:970-980` — authorized access, page
 * view, processing state, expired-access recovery, and no browser cache assumption for
 * sensitive files.
 *
 * **Every object URL it creates is revoked.** `12_Security_RBAC_Audit.md:1557` requires
 * it, and the reason is sharper than tidiness: an object URL is a readable handle to the
 * bytes that survives for the lifetime of the document, so a viewer that leaks them keeps
 * every file a person opened available to any script on the page until they navigate
 * away.
 *
 * **Nothing here touches `localStorage`, IndexedDB or a cache.**
 * `12_Security_RBAC_Audit.md:1555` forbids putting sensitive files or full API responses
 * in any of them, and a service worker is exactly the thing that would otherwise decide
 * to keep a downloaded receipt.
 *
 * The fetch is passed in rather than performed here so the component makes no assumption
 * about credentials, and so a caller that already refuses cross-origin requests keeps
 * that guarantee.
 */

/**
 * Fetch the bytes and hand back a URL together with the call that releases it.
 *
 * Extracted so the revocation rule can be asserted without a DOM: the pairing is the
 * whole safety property, and a caller that receives them together cannot take one and
 * forget the other the way an effect body can.
 */
export async function objectUrlFor(
  load: (fileId: string, signal: AbortSignal) => Promise<Blob>,
  fileId: string,
  signal: AbortSignal,
): Promise<{ readonly url: string; readonly revoke: () => void }> {
  const blob = await load(fileId, signal);
  const url = URL.createObjectURL(blob);
  return { url, revoke: () => URL.revokeObjectURL(url) };
}

export interface SecureFileViewerProps {
  readonly fileId: string;
  /** Fetches the bytes with the caller's own credentials. */
  readonly load: (fileId: string, signal: AbortSignal) => Promise<Blob>;
  readonly labels: {
    readonly loading: string;
    readonly processing: string;
    readonly expired: string;
    readonly retry: string;
    readonly alt: string;
  };
}

type Phase =
  | { readonly name: "loading" }
  | { readonly name: "ready"; readonly url: string }
  | { readonly name: "unavailable" };

export function SecureFileViewer({ fileId, load, labels }: SecureFileViewerProps) {
  const [phase, setPhase] = useState<Phase>({ name: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const abort = new AbortController();
    let created: string | null = null;
    let cancelled = false;

    setPhase({ name: "loading" });

    let release: (() => void) | null = null;

    objectUrlFor(load, fileId, abort.signal)
      .then(({ url, revoke }) => {
        release = revoke;
        if (cancelled) {
          // Created and immediately unwanted: release it here rather than leaving it for
          // the cleanup, which has already run.
          revoke();
          return;
        }
        created = url;
        setPhase({ name: "ready", url });
      })
      .catch(() => {
        if (!cancelled) {
          // A refusal and a not-yet-rendered preview look the same from here, and the
          // honest message covers both: the caller decides what it is by what it asked
          // for. `expired` offers the recovery the specification asks for — asking again
          // — which is also the right move for a preview that has since been rendered.
          setPhase({ name: "unavailable" });
        }
      });

    return () => {
      cancelled = true;
      abort.abort();
      // Revoked on unmount and on every re-run, not only on success. A URL created and
      // then replaced by a second attempt would otherwise stay readable for the life of
      // the document.
      if (created !== null && release !== null) {
        release();
      }
    };
  }, [fileId, load, attempt]);

  if (phase.name === "loading") {
    return <p role="status">{labels.loading}</p>;
  }

  if (phase.name === "unavailable") {
    return (
      <div className="flex items-center gap-3">
        <p data-testid="viewer-unavailable">{labels.expired}</p>
        <button type="button" className="underline" onClick={() => setAttempt((n) => n + 1)}>
          {labels.retry}
        </button>
      </div>
    );
  }

  return (
    <img
      src={phase.url}
      alt={labels.alt}
      data-testid="viewer-image"
      className="max-w-full rounded-md border border-slate-200"
    />
  );
}
