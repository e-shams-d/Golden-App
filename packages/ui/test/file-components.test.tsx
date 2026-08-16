import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  FileUploadPanel,
  exceedsCeiling,
  offersRetry,
  outcomeMessage,
  type UploadOutcome,
} from "../src/file-upload-panel";
import { SecureFileViewer, objectUrlFor } from "../src/secure-file-viewer";

/**
 * Covers: UI-FILE-001, UI-FILE-002, UI-FILE-003, UI-FILE-005.
 *
 * This package renders to static markup and has no DOM-interaction library. Rather than
 * add one to assert a boolean and a revocation, the decisions those obligations are about
 * are plain functions the components call — which is better shape anyway: the rule about
 * retry is a rule, not a rendering, and the pairing of a URL with its release is the
 * safety property rather than the markup around it.
 *
 * UI-FILE-004 and UI-FILE-006 are in `apps/trader-pwa/test/evidence-screen.test.ts`. The
 * second is a claim about the application — does a screen import these. The first is a
 * source scan, which needs to read files, and this package's tsconfig carries no Node
 * types: adding `@types/node` to assert an absence would be a dependency bought for a
 * grep.
 */

const LABELS = {
  choose: "choose",
  uploading: "uploading",
  cancel: "cancel",
  retry: "retry",
  available: "stored",
  quarantined: "held for review",
  failed: "not sent",
  tooLarge: "too large",
  guidance: (types: string, megabytes: number) => `${types} up to ${megabytes}MB`,
};

describe("upload outcomes", () => {
  it("tells a quarantined outcome apart from a failed one", () => {
    // UI-FILE-001. A person told their receipt failed will send it again; a person told
    // it is held for review will ask somebody. Showing one as the other produces the
    // wrong action.
    const quarantined: UploadOutcome = { status: "quarantined", fileId: "f1" };
    const failed: UploadOutcome = { status: "failed", message: "boom" };

    expect(outcomeMessage(quarantined, LABELS)).toBe(LABELS.quarantined);
    expect(outcomeMessage(failed, LABELS)).toBe(LABELS.failed);
    expect(outcomeMessage(quarantined, LABELS)).not.toBe(outcomeMessage(failed, LABELS));
  });

  it("offers retry only for a failure", () => {
    // Retrying a quarantined upload sends the same bytes and gets the same answer.
    expect(offersRetry({ status: "failed", message: "boom" })).toBe(true);
    expect(offersRetry({ status: "quarantined", fileId: "f1" })).toBe(false);
    expect(offersRetry({ status: "available", fileId: "f1" })).toBe(false);
  });

  it("refuses an oversized file before anything is sent", () => {
    // UI-FILE-002's neighbour. The server's refusal is the control; this only spares a
    // person three minutes of sending something that will be refused on arrival.
    expect(exceedsCeiling(1001, 1000)).toBe(true);
    expect(exceedsCeiling(1000, 1000)).toBe(false);
  });

  it("renders the guidance from the server's values rather than its own", () => {
    // UI-FILE-005. POL-006 will replace these numbers, and a limit written into the
    // bundle would need a frontend release to change one of them.
    const markup = renderToStaticMarkup(
      <FileUploadPanel
        acceptedMediaTypes={["application/pdf"]}
        maxBytes={5 * 1024 * 1024}
        upload={async () => ({ status: "available", fileId: "f1" })}
        labels={LABELS}
      />,
    );

    expect(markup).toContain("application/pdf up to 5MB");
    // And the accept attribute is the server's list too, so the file chooser offers what
    // the purpose actually takes.
    expect(markup).toContain('accept="application/pdf"');
  });
});

describe("SecureFileViewer", () => {
  it("hands back the release with the URL, and it works", async () => {
    // UI-FILE-003. An object URL is a readable handle to the bytes that lives as long as
    // the document, so a viewer that leaks them keeps every file a person opened
    // available to any script on the page. Returning the pair together is what stops a
    // caller taking one and forgetting the other.
    const created: string[] = [];
    const revoked: string[] = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation(() => {
      const url = `blob:${created.length}`;
      created.push(url);
      return url;
    });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation((url: string) => {
      revoked.push(url);
    });

    const handle = await objectUrlFor(
      async () => new Blob(["x"]),
      "f1",
      new AbortController().signal,
    );

    expect(created).toEqual([handle.url]);
    expect(revoked).toEqual([]);

    handle.revoke();
    expect(revoked).toEqual([handle.url]);

    vi.restoreAllMocks();
  });

  it("passes the abort signal through to the caller's fetch", async () => {
    // The signal is how a viewer that unmounts stops a download that is still running —
    // otherwise the bytes arrive for a screen nobody is looking at.
    const abort = new AbortController();
    const load = vi.fn(async (_id: string, signal: AbortSignal) => {
      expect(signal).toBe(abort.signal);
      return new Blob(["x"]);
    });

    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    await objectUrlFor(load, "f1", abort.signal);
    expect(load).toHaveBeenCalledOnce();
    vi.restoreAllMocks();
  });

  it("renders a status while loading rather than an empty frame", () => {
    const markup = renderToStaticMarkup(
      <SecureFileViewer
        fileId="f1"
        load={async () => new Blob(["x"])}
        labels={{
          loading: "loading",
          processing: "processing",
          expired: "unavailable",
          retry: "retry",
          alt: "receipt",
        }}
      />,
    );

    expect(markup).toContain("loading");
    expect(markup).toContain('role="status"');
  });
});
