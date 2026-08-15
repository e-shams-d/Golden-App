import { normalizeApiError } from "./api-error";
import type {
  ApiRequestOptions,
  ApiResponse,
  ApiTransport,
  TransportConfig,
} from "./types";

const JSON_MEDIA_TYPE = "application/json";

export function createApiTransport(config: TransportConfig = {}): ApiTransport {
  const baseUrl = normalizeBaseUrl(config.baseUrl ?? "/api/v1");
  const fetchImpl = config.fetchImpl ?? globalThis.fetch;

  if (!fetchImpl) throw new Error("A fetch implementation is required.");

  return {
    async request<TData, TBody = unknown>(
      options: ApiRequestOptions<TBody>,
    ): Promise<ApiResponse<TData>> {
      assertRelativePath(options.path);
      const headers = new Headers({ Accept: JSON_MEDIA_TYPE });

      // `FormData` is the one body this transport must NOT label. A multipart body is
      // only parseable with the boundary token that separates its parts; the boundary is
      // generated when the request is dispatched, so setting `Content-Type` by hand
      // sends the media type with no boundary and the server rejects the body as
      // malformed — which reads like a server fault rather than a client one. The
      // platform sets the full header, and only if this one is absent.
      const multipart = isFormData(options.body);
      if (options.body !== undefined && !multipart) {
        headers.set("Content-Type", JSON_MEDIA_TYPE);
      }
      if (options.idempotencyKey) headers.set("Idempotency-Key", options.idempotencyKey);
      if (options.ifMatch) headers.set("If-Match", options.ifMatch);
      if (options.recentAuthToken) {
        headers.set("X-Recent-Auth", options.recentAuthToken);
      }

      const csrfToken = config.getCsrfToken?.();
      if (csrfToken) headers.set("X-CSRF-Token", csrfToken);

      const response = await fetchImpl(`${baseUrl}${options.path}`, {
        method: options.method,
        headers,
        credentials: config.credentials ?? "same-origin",
        cache: "no-store",
        redirect: "manual",
        ...(options.signal ? { signal: options.signal } : {}),
        ...(options.body !== undefined
          ? { body: multipart ? (options.body as unknown as FormData) : JSON.stringify(options.body) }
          : {}),
      });

      if (response.status === 401) config.onUnauthorized?.();
      if (!response.ok) throw await normalizeApiError(response);

      const etag = response.headers.get("etag") ?? undefined;
      const requestId = response.headers.get("x-request-id") ?? undefined;

      return {
        data: await parseResponse<TData>(response),
        status: response.status,
        ...(etag ? { etag } : {}),
        ...(requestId ? { requestId } : {}),
      };
    },
  };
}

function normalizeBaseUrl(baseUrl: string): string {
  if (!baseUrl.startsWith("/") && !baseUrl.startsWith("https://")) {
    throw new Error("API base URL must be same-origin relative or HTTPS.");
  }
  return baseUrl.replace(/\/$/, "");
}

function isFormData(body: unknown): boolean {
  // Feature-detected rather than `body instanceof FormData`. This module runs in a
  // browser, in Node during tests, and in a Next.js server component, and `FormData` is
  // not guaranteed to be a global in all three — an `instanceof` against a missing
  // global is a ReferenceError, which would turn every JSON request into a crash.
  return typeof FormData !== "undefined" && body instanceof FormData;
}

function assertRelativePath(path: string): void {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("://")) {
    throw new Error("API paths must be origin-relative.");
  }
}

async function parseResponse<TData>(response: Response): Promise<TData> {
  if (response.status === 204) return undefined as TData;
  if (!response.headers.get("content-type")?.includes(JSON_MEDIA_TYPE)) {
    throw new Error("The API returned an unsupported media type.");
  }
  return (await response.json()) as TData;
}
