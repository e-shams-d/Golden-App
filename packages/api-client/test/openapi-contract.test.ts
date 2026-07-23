import { describe, expect, expectTypeOf, it, vi } from "vitest";

import {
  createApiTransport,
  createTypedApiClient,
  type ApiErrorEnvelope,
  type ApiOperationResponse,
  type GeneratedApiComponents,
  type GeneratedApiOperations,
  type GeneratedApiPaths,
} from "../src";

describe("generated M1 OpenAPI contract", () => {
  it("contains the stable non-financial runtime routes", () => {
    type HasLiveRoute =
      "/api/v1/health/live" extends keyof GeneratedApiPaths ? true : false;
    type HasReleaseRoute =
      "/api/v1/meta/release" extends keyof GeneratedApiPaths ? true : false;

    expectTypeOf<HasLiveRoute>().toEqualTypeOf<true>();
    expectTypeOf<HasReleaseRoute>().toEqualTypeOf<true>();
    expectTypeOf<GeneratedApiOperations["getHealthReadiness"]>().toBeObject();
    expectTypeOf<
      GeneratedApiComponents["schemas"]["ErrorEnvelope"]
    >().toBeObject();
    expectTypeOf<ApiErrorEnvelope>().toEqualTypeOf<
      Readonly<GeneratedApiComponents["schemas"]["ErrorEnvelope"]>
    >();
  });

  it("does not freeze unresolved financial endpoints", () => {
    type HasPrematureFinancialRoute =
      "/api/v1/payment-requests" extends keyof GeneratedApiPaths ? true : false;

    expectTypeOf<HasPrematureFinancialRoute>().toEqualTypeOf<false>();
  });

  it("infers a response and delegates through the hardened transport", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      new Response(
        JSON.stringify({
          service: "backend-api",
          status: "alive",
          version: "0.1.0",
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );
    const client = createTypedApiClient(createApiTransport({ fetchImpl }));
    const response = await client.request("/api/v1/health/live", "get");

    expectTypeOf(response.data).toEqualTypeOf<
      ApiOperationResponse<"/api/v1/health/live", "get">
    >();
    expect(response.data.status).toBe("alive");
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/v1/health/live",
      expect.objectContaining({ method: "GET", redirect: "manual" }),
    );
  });
});
