import type { components as GeneratedApiComponents } from "./generated/openapi";

export type HttpMethod =
  | "GET"
  | "POST"
  | "PATCH"
  | "PUT"
  | "DELETE"
  | "HEAD"
  | "OPTIONS";

export type ApiRequestOptions<TBody = unknown> = Readonly<{
  method: HttpMethod;
  path: `/${string}`;
  body?: TBody;
  idempotencyKey?: string;
  ifMatch?: string;
  recentAuthToken?: string;
  signal?: AbortSignal;
}>;

export type ApiResponse<TData> = Readonly<{
  data: TData;
  status: number;
  etag?: string;
  requestId?: string;
}>;

export type ApiErrorEnvelope = Readonly<
  GeneratedApiComponents["schemas"]["ErrorEnvelope"]
>;
export type ApiErrorBody = Readonly<ApiErrorEnvelope["error"]>;
export type ApiErrorDetail = Readonly<ApiErrorBody["details"][number]>;

export type ApiErrorPayload = Readonly<{
  code?: string;
  message?: string;
  details?: readonly ApiErrorDetail[];
  fieldErrors?: Record<string, string[]>;
  requestId?: string;
}>;

export type TransportConfig = Readonly<{
  baseUrl?: string;
  credentials?: RequestCredentials;
  fetchImpl?: typeof fetch;
  getCsrfToken?: () => string | undefined;
  onUnauthorized?: () => void;
}>;

export type ApiTransport = Readonly<{
  request: <TData, TBody = unknown>(
    options: ApiRequestOptions<TBody>,
  ) => Promise<ApiResponse<TData>>;
}>;
