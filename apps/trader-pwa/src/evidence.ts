import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

// The same construction `auth.ts` uses. Built here rather than exported from there so
// that this module's dependency is the transport rather than the auth adapter, which it
// has no business reaching into.
const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/**
 * Uploading a receipt, and reading it back.
 *
 * The purpose is fixed to `incoming_payment_receipt` because that is the only thing a
 * goldsmith uploads in M4 — the payment-request path is M5. Fixing it here rather than
 * letting the screen choose means the screen cannot ask for a purpose the trader has no
 * business using.
 */

export interface UploadLimits {
  readonly acceptedMediaTypes: readonly string[];
  readonly maxBytes: number;
}

/**
 * What the purpose accepts, as the server states it.
 *
 * Hard-coding these would put POL-006's numbers in the bundle, and changing a limit would
 * then need a frontend release. They are constants here only until a limits endpoint
 * exists; the panel takes them as props either way, so that endpoint changes one line.
 */
export const RECEIPT_LIMITS: UploadLimits = {
  acceptedMediaTypes: ["application/pdf", "image/jpeg", "image/png"],
  maxBytes: 10 * 1024 * 1024,
};

export interface UploadedFile {
  readonly id: string;
  readonly status: string;
}

export async function uploadReceipt(file: File, signal: AbortSignal): Promise<UploadedFile> {
  const body = new FormData();
  body.append("purpose", "incoming_payment_receipt");
  body.append("file", file, file.name);

  const response = await transport.request<UploadedFile, FormData>({
    method: "POST",
    path: "/files",
    body,
    // Required by the command catalogue. Generated per attempt rather than per file: two
    // attempts at the same document are two uploads, and a retry after a failure must not
    // be mistaken for the first one succeeding.
    idempotencyKey: crypto.randomUUID(),
    signal,
  });

  return response.data;
}

export async function loadFileBytes(fileId: string, signal: AbortSignal): Promise<Blob> {
  // Not through the typed client: it parses every response as JSON and refuses anything
  // else, which is correct for every other route and wrong for one that returns bytes.
  const response = await fetch(`/api/v1/files/${fileId}/download`, {
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error(`download refused with ${response.status}`);
  }
  return response.blob();
}
