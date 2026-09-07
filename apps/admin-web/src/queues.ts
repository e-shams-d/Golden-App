/**
 * The work waiting for a person.
 * `21_UI_Design_System_and_Screen_Specification.md` §10.3, `15_Agent_Implementation_Plan.md:1348`.
 *
 * M11 Screens, slice 2. Sixteen queues have had routes since M11 slices 2–5 and nothing has opened
 * one.
 *
 * **Admin only, and there is no trader half of this module.** §19.2's four queue roles —
 * accountant, manager, warehouse operator, technical admin — are all staff. A trader has requests
 * and orders, not queues, so `UI-ISO-001` is satisfied here by there being nothing to duplicate
 * rather than by duplicating it.
 *
 * **No list of queues is written down in this app.** `GET /api/v1/queues` returns the ones the
 * session's grants allow, each with its own filter and sort allowlist, so the screen never holds a
 * copy of the registry — which would be sixteen names and thirty-two allowlists kept in step with
 * the backend by nobody. The one thing this app does hold is a Persian label per queue, and
 * `tests/backend/test_queue_screens_exist.py` fails when a built queue has none.
 *
 * **Which queues a person sees is the server's answer, not a filter applied here.** §20.1 `:2114`:
 * frontend visibility is not authorization. A queue absent from the index is one whose page
 * answers 403, and `tests/integration/test_queue_index.py` asserts that rather than trusting it.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** One queue this session may open, exactly as the index publishes it. */
export type QueueListing = Readonly<{
  name: string;
  waiting: number;
  /** The filter keys this queue accepts. Rendering a control for anything else earns a 400. */
  filters: readonly string[];
  /** The sortable field names, in the spec's declaration order. */
  sorts: readonly string[];
  /** What the route orders by when the request names no sort. Always one of `sorts`. */
  default_sort: string;
  /**
   * Where a row of this queue is opened — a path prefix the row's `id` is appended to — or `null`
   * when no screen exists for it yet.
   *
   * **The server's answer, for the same reason the filter allowlist is.** Sixteen queue names
   * mapped to sixteen destinations in this app would be a copy of the backend registry, and its
   * failure mode is a link to the *wrong screen for the right row*: an accountant opening somebody
   * else's work believing it was theirs. `null` renders no link, which is the honest rendering of
   * "this queue's rows have nowhere to go yet".
   */
  detail_path: string | null;
}>;

export type QueueIndex = Readonly<{
  items: readonly QueueListing[];
  total: number;
}>;

/**
 * One row of any queue. **The same five fields for all sixteen**, which is what lets one table
 * component serve every queue — the payoff of the backend's decision to make `QueueRow` narrow.
 *
 * `trader_id` is nullable because not every queue is about one business: a batch version spans
 * many and a maintenance task belongs to none.
 */
export type QueueRow = Readonly<{
  id: string;
  reference: string;
  status: string;
  created_at: string;
  trader_id: string | null;
}>;

export type QueuePage = Readonly<{
  queue: string;
  items: readonly QueueRow[];
  next_cursor: string | null;
  /**
   * How much work is waiting behind the cursor, from the server.
   *
   * Never `items.length`. §2.3 `:205` — server truth over visual state — and here the two differ
   * by construction: a page is at most `limit` rows and the queue is however long it is.
   */
  total: number;
}>;

export async function listQueues(signal?: AbortSignal): Promise<QueueIndex> {
  const response = await transport.request<QueueIndex>({
    method: "GET",
    path: "/queues",
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

export type QueueQuery = Readonly<{
  /** Allowlisted per queue by the server. Only keys from that queue's `filters` are sent. */
  filters?: Readonly<Record<string, string>>;
  sort?: string;
  cursor?: string | null;
  limit?: number;
}>;

/**
 * Read one page of one queue.
 *
 * **A cursor, never an offset.** An offset re-reads from the top on every page, so rows shift under
 * somebody draining a queue and items are skipped or seen twice — in the one place that cannot
 * tolerate it, because the purpose is to work through every row exactly once. The server declares
 * no offset parameter and ignores one if sent; this module has no way to construct one, which is
 * the half that is checkable from here.
 */
export async function readQueue(
  name: string,
  query: QueueQuery = {},
  signal?: AbortSignal,
): Promise<QueuePage> {
  const parameters = new URLSearchParams();
  for (const [key, value] of Object.entries(query.filters ?? {})) {
    // Empty means "no filter" rather than "filter on the empty string". The server would refuse
    // an empty value on a uuid filter with a 400, which is a correct refusal of a question the
    // screen should not have asked.
    if (value !== "") parameters.set(key, value);
  }
  if (query.sort) parameters.set("sort", query.sort);
  if (query.cursor) parameters.set("cursor", query.cursor);
  if (query.limit !== undefined) parameters.set("limit", String(query.limit));

  const suffix = parameters.size > 0 ? `?${parameters.toString()}` : "";
  const response = await transport.request<QueuePage>({
    method: "GET",
    path: `/queues/${encodeURIComponent(name)}${suffix}`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}
