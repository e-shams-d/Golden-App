import type { operations, paths } from "./generated/openapi";
import type {
  ApiRequestOptions,
  ApiResponse,
  ApiTransport,
  HttpMethod,
} from "./types";

const API_V1_PREFIX = "/api/v1";

type GeneratedMethod = Lowercase<HttpMethod>;
type OperationControls = Pick<
  ApiRequestOptions<never>,
  "idempotencyKey" | "ifMatch" | "recentAuthToken" | "signal"
>;
type OperationAt<
  TPath extends ApiPath,
  TMethod extends ApiMethodForPath<TPath>,
> = TMethod extends keyof paths[TPath] ? paths[TPath][TMethod] : never;
type MediaData<TContent> = TContent extends {
  "application/json": infer TData;
}
  ? TData
  : TContent extends object
    ? TContent[keyof TContent]
    : never;
type RequestBodyData<TOperation> = TOperation extends {
  requestBody?: infer TRequestBody;
}
  ? TRequestBody extends { content: infer TContent }
    ? MediaData<TContent>
    : never
  : never;
type SuccessStatus = `${2}${number}${number}` | 200 | 201 | 202 | 203 | 204 | 205 | 206;
type SuccessResponse<TOperation> = TOperation extends {
  responses: infer TResponses;
}
  ? TResponses[Extract<keyof TResponses, SuccessStatus>]
  : never;
type ResponseData<TResponse> = TResponse extends { content: infer TContent }
  ? [TContent] extends [never]
    ? undefined
    : MediaData<TContent>
  : undefined;
type RequiredKeys<TValue> = {
  [TKey in keyof TValue]-?: object extends Pick<TValue, TKey> ? never : TKey;
}[keyof TValue];
type ParametersOption<TOperation> = TOperation extends {
  parameters: infer TParameters;
}
  ? { parameters: TParameters }
  : TOperation extends { parameters?: infer TParameters }
    ? { parameters?: TParameters }
    : { parameters?: never };
type BodyOption<TOperation> = TOperation extends {
  requestBody: { content: infer TContent };
}
  ? { body: MediaData<TContent> }
  : TOperation extends { requestBody?: { content: infer TContent } }
    ? { body?: MediaData<TContent> }
    : { body?: never };

export type ApiPath = keyof paths & string;
export type ApiMethodForPath<TPath extends ApiPath> = Extract<
  keyof paths[TPath],
  GeneratedMethod
>;
export type ApiOperation<
  TPath extends ApiPath,
  TMethod extends ApiMethodForPath<TPath>,
> = OperationAt<TPath, TMethod>;
export type ApiOperationById<TId extends keyof operations> = operations[TId];
export type ApiOperationParameters<
  TPath extends ApiPath,
  TMethod extends ApiMethodForPath<TPath>,
> = OperationAt<TPath, TMethod> extends { parameters?: infer TParameters }
  ? TParameters
  : never;
export type ApiOperationBody<
  TPath extends ApiPath,
  TMethod extends ApiMethodForPath<TPath>,
> = RequestBodyData<OperationAt<TPath, TMethod>>;
export type ApiOperationResponse<
  TPath extends ApiPath,
  TMethod extends ApiMethodForPath<TPath>,
> = ResponseData<SuccessResponse<OperationAt<TPath, TMethod>>>;
export type ApiOperationOptions<
  TPath extends ApiPath,
  TMethod extends ApiMethodForPath<TPath>,
> = Readonly<
  OperationControls &
    ParametersOption<OperationAt<TPath, TMethod>> &
    BodyOption<OperationAt<TPath, TMethod>>
>;

type RequestArguments<
  TPath extends ApiPath,
  TMethod extends ApiMethodForPath<TPath>,
  TOptions extends ApiOperationOptions<TPath, TMethod> = ApiOperationOptions<
    TPath,
    TMethod
  >,
> = [RequiredKeys<TOptions>] extends [never]
  ? [options?: TOptions]
  : [options: TOptions];

export type TypedApiClient = Readonly<{
  request: <
    TPath extends ApiPath,
    TMethod extends ApiMethodForPath<TPath>,
  >(
    path: TPath,
    method: TMethod,
    ...arguments_: RequestArguments<TPath, TMethod>
  ) => Promise<ApiResponse<ApiOperationResponse<TPath, TMethod>>>;
}>;

export function createTypedApiClient(transport: ApiTransport): TypedApiClient {
  return {
    async request<
      TPath extends ApiPath,
      TMethod extends ApiMethodForPath<TPath>,
    >(
      path: TPath,
      method: TMethod,
      ...arguments_: RequestArguments<TPath, TMethod>
    ): Promise<ApiResponse<ApiOperationResponse<TPath, TMethod>>> {
      const options = (arguments_[0] ?? {}) as ApiOperationOptions<TPath, TMethod>;
      const parameters = readParameterGroups(options);
      rejectUnsafeParameterGroups(parameters);
      const requestPath = buildRequestPath(path, parameters);
      const body = "body" in options ? options.body : undefined;
      return transport.request<ApiOperationResponse<TPath, TMethod>, typeof body>({
        method: method.toUpperCase() as HttpMethod,
        path: requestPath,
        ...(body !== undefined ? { body } : {}),
        ...(options.idempotencyKey
          ? { idempotencyKey: options.idempotencyKey }
          : {}),
        ...(options.ifMatch ? { ifMatch: options.ifMatch } : {}),
        ...(options.recentAuthToken
          ? { recentAuthToken: options.recentAuthToken }
          : {}),
        ...(options.signal ? { signal: options.signal } : {}),
      });
    },
  };
}

function readParameterGroups(options: object): Record<string, unknown> {
  if (!("parameters" in options) || options.parameters === undefined) return {};
  if (!isRecord(options.parameters)) {
    throw new Error("Operation parameters must be an object.");
  }
  return options.parameters;
}

function rejectUnsafeParameterGroups(parameters: Record<string, unknown>): void {
  for (const location of ["header", "cookie"]) {
    if (!(location in parameters) || parameters[location] === undefined) continue;
    if (!isRecord(parameters[location])) {
      throw new Error(`${location} parameters must be an object.`);
    }
    if (Object.keys(parameters[location]).length > 0) {
      throw new Error(
        `${location} parameters are not forwarded by the secure typed client.`,
      );
    }
  }
}

function buildRequestPath(
  contractPath: string,
  parameters: Record<string, unknown>,
): `/${string}` {
  if (!contractPath.startsWith(`${API_V1_PREFIX}/`)) {
    throw new Error("Typed API paths must stay inside /api/v1.");
  }
  let path = contractPath.slice(API_V1_PREFIX.length);
  const pathParameters = isRecord(parameters.path) ? parameters.path : {};
  for (const [name, value] of Object.entries(pathParameters)) {
    path = path.replaceAll(
      `{${name}}`,
      encodeURIComponent(serializePrimitive(value, `path parameter ${name}`)),
    );
  }
  if (path.includes("{") || path.includes("}")) {
    throw new Error("A required path parameter is missing.");
  }

  const queryParameters = isRecord(parameters.query) ? parameters.query : {};
  const query = new URLSearchParams();
  for (const [name, rawValue] of Object.entries(queryParameters)) {
    if (rawValue === undefined) continue;
    const values = Array.isArray(rawValue) ? rawValue : [rawValue];
    for (const value of values) {
      query.append(name, serializePrimitive(value, `query parameter ${name}`));
    }
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  return `${path}${suffix}` as `/${string}`;
}

function serializePrimitive(value: unknown, context: string): string {
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }
  if (value === null) return "";
  throw new Error(`${context} must be a scalar or an array of scalars.`);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
