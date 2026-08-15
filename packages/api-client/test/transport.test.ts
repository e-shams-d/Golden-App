import { describe, expect, it, vi } from "vitest";

import { createApiTransport } from "../src";

describe("API transport", () => {
  it("sends command guards and disables HTTP caching without replay", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: {
          "content-type": "application/json",
          etag: '"rv-8"',
          "x-request-id": "request-1",
        },
      }),
    );
    const transport = createApiTransport({ fetchImpl });

    const result = await transport.request<{ ok: boolean }, { value: string }>({
      method: "POST",
      path: "/commands/example",
      body: { value: "1000" },
      idempotencyKey: "logical-command-1",
      ifMatch: '"rv-7"',
      recentAuthToken: "short-lived-context",
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const init = fetchImpl.mock.calls[0]?.[1];
    const headers = new Headers(init?.headers);
    expect(init?.cache).toBe("no-store");
    expect(headers.get("Idempotency-Key")).toBe("logical-command-1");
    expect(headers.get("If-Match")).toBe('"rv-7"');
    expect(result.etag).toBe('"rv-8"');
  });

  it("normalizes the canonical backend error envelope and field details", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      new Response(
        JSON.stringify({
          error: {
            code: "VALIDATION_ERROR",
            message: "One or more fields are invalid.",
            details: [
              { field: "amount", reason: "Must be a positive integer." },
              { field: "amount", reason: "Must use IRR." },
              { field: null, reason: "Request validation failed." },
              { reason: "Optional contract field may be omitted." },
            ],
            request_id: "request-from-body",
          },
        }),
        {
          status: 422,
          headers: {
            "content-type": "application/json",
            "x-request-id": "request-from-header",
          },
        },
      ),
    );
    const transport = createApiTransport({ fetchImpl });

    await expect(
      transport.request({ method: "POST", path: "/commands/example" }),
    ).rejects.toMatchObject({
      status: 422,
      code: "VALIDATION_ERROR",
      requestId: "request-from-body",
      fieldErrors: {
        amount: ["Must be a positive integer.", "Must use IRR."],
      },
    });
  });

  it("does not label a multipart body, so the platform can add the boundary", async () => {
    // A multipart body is only parseable with the boundary token that separates its
    // parts, and the boundary is generated when the request is dispatched. Setting
    // `Content-Type` by hand sends the media type with no boundary, and the server
    // rejects the body as malformed — which reads like a server fault, not a client one.
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ id: "file-1" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      }),
    );
    const transport = createApiTransport({ fetchImpl });

    const body = new FormData();
    body.append("purpose", "incoming_payment_receipt");
    body.append("file", new Blob([new Uint8Array([1, 2, 3])]), "receipt.png");

    await transport.request<{ id: string }, FormData>({
      method: "POST",
      path: "/files",
      body,
      idempotencyKey: "upload-1",
    });

    const init = fetchImpl.mock.calls[0]?.[1];
    expect(new Headers(init?.headers).get("Content-Type")).toBeNull();
    // Passed through untouched. `JSON.stringify(FormData)` yields "{}", which would send
    // an empty request the server could only report as a missing-file validation error
    // on a file the caller believes it attached.
    expect(init?.body).toBe(body);
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("upload-1");
  });

  it("still labels an ordinary JSON body", async () => {
    // The other direction, and what keeps the multipart case an exception: a transport
    // that stopped labelling everything would send JSON with no content type.
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const transport = createApiTransport({ fetchImpl });

    await transport.request<{ ok: boolean }, { value: string }>({
      method: "POST",
      path: "/commands/example",
      body: { value: "1000" },
    });

    const init = fetchImpl.mock.calls[0]?.[1];
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(init?.body).toBe(JSON.stringify({ value: "1000" }));
  });
});
