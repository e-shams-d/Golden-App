/**
 * What the system has told this member of staff.
 * `21_UI_Design_System_and_Screen_Specification.md:2196`.
 *
 * M11 Screens, slice 1. The table has existed since M9 and the routes since M11 slice 1 of the
 * backend; nothing has ever rendered a row.
 *
 * **Per-app, and duplicated on the trader side rather than shared.** `UI-ISO-001` requires that
 * neither bundle contain the other's endpoint paths, and the cheapest guarantee is that neither
 * ever names one. Notifications are the first surface where **both audiences call the same path**,
 * which makes a shared module look obviously right — and it is exactly the case the rule exists
 * for: a shared module is one import away from carrying the other side's paths the first time
 * somebody adds a helper to it. Two files with one path each is the cheaper mistake.
 *
 * **No permission is consulted here and none exists.** `permission_catalog.yaml` has no
 * notification permission; the backend scopes by `recipient_actor_id`, taken from the session. A
 * screen that filtered by anything would be inventing a control the server does not have.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** One message, exactly as the contract publishes it. */
export type Notification = Readonly<{
  id: string;
  notification_type: string;
  title: string;
  body: string;
  entity_type: string;
  entity_id: string;
  status: string;
  read_at: string | null;
  created_at: string;
}>;

export type NotificationPage = Readonly<{
  items: readonly Notification[];
  next_cursor: string | null;
  /**
   * The server's count, and the only one this app displays.
   *
   * §2.3 `:205` — server truth over visual state. Counting unread items in `items` would be a
   * second definition that disagrees the moment a page is not the whole list, which is the
   * ordinary case rather than an edge one.
   */
  unread_count: number;
}>;

export async function listNotifications(
  cursor?: string | null,
  signal?: AbortSignal,
): Promise<NotificationPage> {
  const response = await transport.request<NotificationPage>({
    method: "GET",
    path: cursor
      ? `/notifications?cursor=${encodeURIComponent(cursor)}`
      : "/notifications",
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * Mark one read.
 *
 * **No `If-Match` and no idempotency key**, because the backend requires neither: reading a
 * message is not a financial mutation, and the command is idempotent by construction — a second
 * call returns the row unchanged rather than moving `read_at`. Sending a precondition the server
 * does not check would be a screen inventing a contract.
 */
export async function markRead(notificationId: string): Promise<Notification> {
  const response = await transport.request<Notification>({
    method: "POST",
    path: `/notifications/${notificationId}/mark-read`,
  });
  return response.data;
}

export async function markAllRead(): Promise<{ marked: number; unread_count: number }> {
  const response = await transport.request<{ marked: number; unread_count: number }>({
    method: "POST",
    path: "/notifications/mark-all-read",
  });
  return response.data;
}
