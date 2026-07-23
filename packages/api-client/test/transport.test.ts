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
});
