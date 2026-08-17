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

  // M5 slice 3 resolves this endpoint's shape, so the assertion flips rather than
  // being deleted. The guard's purpose was never "payment requests must not exist" —
  // it was "do not publish a financial contract whose design is unresolved", written
  // when `payment_requests` had no table, no columns and no permission. Document 04's
  // 11.1 and 11.2 and document 05's section 15 now define it, and it is migrated.
  //
  // Deleting the case would have removed the only statement of that rule. Flipping it
  // keeps the rule and moves the line.
  it("publishes the payment-request endpoints whose shape is now resolved", () => {
    type HasRequestCollection =
      "/api/v1/payment-requests" extends keyof GeneratedApiPaths ? true : false;

    expectTypeOf<HasRequestCollection>().toEqualTypeOf<true>();
    expectTypeOf<GeneratedApiOperations["createPaymentRequestDraft"]>().toBeObject();
    expectTypeOf<GeneratedApiOperations["cancelPaymentRequest"]>().toBeObject();
  });

  it("still does not publish the endpoints M5 has not built", () => {
    // The other half of the original guard, kept explicit. Submission, revisions and
    // review arrive in slices 5 to 7 and batching is M6; their request and response
    // shapes are not settled, so a generated client must not be able to call them.
    type HasSubmit =
      "/api/v1/payment-requests/{payment_request_id}/submit" extends keyof GeneratedApiPaths
        ? true
        : false;
    type HasRevisions =
      "/api/v1/payment-requests/{payment_request_id}/revisions" extends keyof GeneratedApiPaths
        ? true
        : false;

    expectTypeOf<HasSubmit>().toEqualTypeOf<false>();
    expectTypeOf<HasRevisions>().toEqualTypeOf<false>();
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
