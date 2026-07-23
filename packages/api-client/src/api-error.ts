import type {
  ApiErrorDetail,
  ApiErrorEnvelope,
  ApiErrorPayload,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: readonly ApiErrorDetail[] | undefined;
  readonly fieldErrors: Record<string, string[]> | undefined;
  readonly requestId: string | undefined;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message ?? "درخواست با خطا روبه‌رو شد.");
    this.name = "ApiError";
    this.status = status;
    this.code = payload.code ?? "UNKNOWN_ERROR";
    this.details = payload.details;
    this.fieldErrors = payload.fieldErrors;
    this.requestId = payload.requestId;
  }
}

export async function normalizeApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("x-request-id") ?? undefined;
  let payload: ApiErrorPayload = {};

  if (response.headers.get("content-type")?.includes("application/json")) {
    const candidate: unknown = await response.json().catch(() => undefined);
    if (isErrorEnvelope(candidate)) {
      const body = candidate.error;
      const fieldErrors = collectFieldErrors(body.details);
      payload = {
        code: body.code,
        message: body.message,
        details: body.details,
        requestId: body.request_id,
        ...(fieldErrors ? { fieldErrors } : {}),
      };
    }
  }

  return new ApiError(response.status, {
    ...payload,
    ...(requestId && !payload.requestId ? { requestId } : {}),
  });
}

function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (!isRecord(value) || !isRecord(value.error)) return false;
  const { code, message, details, request_id: requestId } = value.error;
  return (
    typeof code === "string" &&
    typeof message === "string" &&
    typeof requestId === "string" &&
    Array.isArray(details) &&
    details.every(isErrorDetail)
  );
}

function isErrorDetail(value: unknown): value is ApiErrorDetail {
  return (
    isRecord(value) &&
    (value.field === undefined ||
      typeof value.field === "string" ||
      value.field === null) &&
    typeof value.reason === "string"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function collectFieldErrors(
  details: readonly ApiErrorDetail[],
): Record<string, string[]> | undefined {
  const fieldErrors: Record<string, string[]> = {};
  for (const detail of details) {
    if (!detail.field) continue;
    (fieldErrors[detail.field] ??= []).push(detail.reason);
  }
  return Object.keys(fieldErrors).length > 0 ? fieldErrors : undefined;
}
