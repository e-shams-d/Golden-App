"use client";

import { t } from "@gold/localization";
import { StateView } from "@gold/ui";
import { useCallback, useEffect, useState } from "react";

import { TraderShell } from "../../components/trader-shell";
import {
  listNotifications,
  markAllRead,
  markRead,
  type Notification,
} from "../../src/notifications";

/**
 * What the centre has told this business.
 * `21_UI_Design_System_and_Screen_Specification.md:2196`.
 *
 * M11 Screens, slice 1. M9 decided that a failed payment reaches its trader **as a notification
 * rather than as a publication**, and M10 added a second producer for gold ready to dispatch. Both
 * have been writing rows since; this is the first screen that renders one.
 *
 * **The unread count comes from the server, never from counting this page.** §2.3 `:205` — server
 * truth over visual state. A count derived from `items` would disagree the moment the list is
 * longer than one page, which is the ordinary case rather than an edge one.
 *
 * **Marking read re-reads rather than editing the row in place.** The optimistic version — flip
 * the status locally and decrement a local count — is shorter and wrong in a way that only shows
 * up under a failure: if the request fails the screen has already told the person it succeeded.
 * Re-reading costs one round trip and cannot lie.
 *
 * **A notification is never workflow truth**, which `audit_outbox_catalog.yaml` states as a flag
 * and this screen honours by having no action other than "read". There is deliberately no button
 * here that acknowledges a publication or resolves a task; those live on the screens that own
 * them, reached through the entity the notification names.
 */

type Phase =
  | { readonly kind: "loading" }
  | {
      readonly kind: "ready";
      readonly items: readonly Notification[];
      readonly unread: number;
    }
  | { readonly kind: "failed" };

export default function TraderNotificationsPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    const page = await listNotifications(null, signal);
    return { kind: "ready", items: page.items, unread: page.unread_count } as const;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((ready) => setPhase(ready))
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, [load]);

  const refresh = async () => {
    try {
      setPhase(await load());
    } catch {
      setPhase({ kind: "failed" });
    }
  };

  const readOne = async (id: string) => {
    setBusy(true);
    try {
      await markRead(id);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const readAll = async () => {
    setBusy(true);
    try {
      await markAllRead();
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <TraderShell>
      <section aria-labelledby="notifications-heading" className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <h1 id="notifications-heading" className="text-xl font-semibold">
            {t("notifications.title")}
          </h1>
          {phase.kind === "ready" && phase.unread > 0 ? (
            <button
              type="button"
              onClick={readAll}
              disabled={busy}
              className="rounded border px-3 py-1 text-sm"
            >
              {t("notifications.markAllRead")}
            </button>
          ) : null}
        </div>

        {phase.kind === "loading" ? (
          <StateView
            kind="loading"
            headingLevel={2}
            title={t("state.loading.title")}
            description={t("state.loading.description")}
          />
        ) : null}
        {phase.kind === "failed" ? (
          <StateView
            kind="error"
            headingLevel={2}
            title={t("state.error.title")}
            description={t("state.error.description")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            {/* The count is announced rather than only drawn: a number that only exists as a
                colour is a number a screen reader user does not have. */}
            <p aria-live="polite">
              {t("notifications.unreadCount")}: {phase.unread}
            </p>

            {phase.items.length === 0 ? (
              <StateView
                kind="empty"
                headingLevel={2}
                title={t("notifications.emptyTitle")}
                description={t("notifications.emptyDescription")}
              />
            ) : (
              <ul className="space-y-3">
                {phase.items.map((notification) => (
                  <li
                    key={notification.id}
                    className="rounded border p-3"
                    // The state is in the markup, not only in the styling, for the same reason
                    // the count is announced.
                    data-status={notification.status}
                  >
                    <p className="font-medium">{notification.title}</p>
                    <p className="text-sm">{notification.body}</p>
                    <p className="text-xs opacity-70">{notification.created_at}</p>
                    {notification.status === "unread" ? (
                      <button
                        type="button"
                        onClick={() => readOne(notification.id)}
                        disabled={busy}
                        className="mt-2 rounded border px-2 py-1 text-xs"
                      >
                        {t("notifications.markRead")}
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : null}
      </section>
    </TraderShell>
  );
}
