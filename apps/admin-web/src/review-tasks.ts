/**
 * The queue item somebody has to decide about. `05_API_Specification.md` §22.1.
 *
 * M11 Screens, slice 9 — the gap slice 8's own gate made visible. `reconciliation-tasks` is built,
 * permission-aware and shown on the dashboard, and its `detail_path` was `None`: an accountant
 * could see that work was waiting and could not open it. A queue that shows rows and opens nothing
 * is worse than one that is missing, because it reports work nobody can do.
 *
 * **The resolution vocabulary comes from the server.** `TaskDetail.accepted_resolution_codes` is
 * the catalogue's list, published on the row itself — so the screen offers what the command
 * accepts rather than a copy that drifts. M8 built it for exactly this reason and nothing had used
 * it.
 *
 * **Every command echoes the `ETag`** that `GET /manual-review-tasks/{task_id}` issues. That read
 * had no ETag until slice 5's contract-wide gate found three routes missing one; this is the first
 * screen to use the one it gained.
 *
 * **Two permissions across four commands, and that is the catalogue's shape.** `manual_review.read`
 * reads; `.assign` covers assigning and starting — beginning work is the same authority as
 * deciding who does it; `.resolve` covers resolving and cancelling, because both end a queue item.
 * The screen offers all four and the server refuses; §20.1.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

function commandKey(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * One queue item.
 *
 * `entity_type` and `entity_id` are for navigation and nothing else — §13.1. This screen shows
 * them so a person can find the subject; it does not resolve them, because no read here joins
 * through them and inventing one would be a second way to reach a row.
 */
export type ReviewTask = Readonly<{
  id: string;
  task_type: string;
  priority: number;
  status: string;
  entity_type: string;
  entity_id: string;
  assigned_to: string | null;
  title: string;
  description: string | null;
  due_at: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_code: string | null;
  resolution_note: string | null;
  record_version: number;
  created_at: string;
  updated_at: string;
  /** What the command will accept. The server's list, so the screen cannot offer an invented one. */
  accepted_resolution_codes: readonly string[];
}>;

export type TaskWithPrecondition = Readonly<{
  task: ReviewTask;
  ifMatch: string;
}>;

export async function readTask(
  taskId: string,
  signal?: AbortSignal,
): Promise<TaskWithPrecondition> {
  const response = await transport.request<ReviewTask>({
    method: "GET",
    path: `/manual-review-tasks/${taskId}`,
    ...(signal ? { signal } : {}),
  });
  if (!response.etag) {
    throw new Error("the read returned no ETag, so no command can be sent safely");
  }
  return { task: response.data, ifMatch: response.etag };
}

/**
 * Assign the item to somebody.
 *
 * **`If-Match` and no idempotency key**, which is the contract's judgement rather than an
 * oversight: assigning to the same person twice is the same state, so a key would be ceremony.
 * A shared queue is where the precondition earns its keep — two people opening the same item is
 * the normal case.
 */
export async function assignTask(
  taskId: string,
  ifMatch: string,
  assigneeAdminUserId: string,
): Promise<ReviewTask> {
  const response = await transport.request<ReviewTask, { assignee_admin_user_id: string }>({
    method: "POST",
    path: `/manual-review-tasks/${taskId}/assign`,
    body: { assignee_admin_user_id: assigneeAdminUserId },
    ifMatch,
  });
  return response.data;
}

/** Begin work. No body and no key, for the same reason assigning has none. */
export async function startTask(taskId: string, ifMatch: string): Promise<ReviewTask> {
  const response = await transport.request<ReviewTask>({
    method: "POST",
    path: `/manual-review-tasks/${taskId}/start`,
    ifMatch,
  });
  return response.data;
}

/**
 * Record what was decided.
 *
 * **`resolution_code` is required and constrained to the catalogue.** A free-text resolution is
 * one nothing can group, and the whole value of a queue is being able to ask what happened to the
 * items in it — which is why the screen renders `accepted_resolution_codes` rather than a list of
 * its own. This is the opposite of the dispute reason in slice 3, and the difference is real: there
 * the catalogue names no set and the audience is a customer; here the catalogue names one and the
 * audience is staff.
 */
export async function resolveTask(
  taskId: string,
  ifMatch: string,
  resolutionCode: string,
  resolutionNote?: string | null,
): Promise<ReviewTask> {
  const response = await transport.request<ReviewTask, Record<string, unknown>>({
    method: "POST",
    path: `/manual-review-tasks/${taskId}/resolve`,
    body: { resolution_code: resolutionCode, resolution_note: resolutionNote ?? null },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}

/** End the item without deciding it. A reason is required: §8.8 wants actor, time and reason. */
export async function cancelTask(
  taskId: string,
  ifMatch: string,
  reason: string,
): Promise<ReviewTask> {
  const response = await transport.request<ReviewTask, { reason: string }>({
    method: "POST",
    path: `/manual-review-tasks/${taskId}/cancel`,
    body: { reason },
    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}
