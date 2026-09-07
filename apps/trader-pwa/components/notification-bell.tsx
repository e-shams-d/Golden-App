"use client";

import { t } from "@gold/localization";
import { Icon } from "@gold/ui";
import Link from "next/link";
import { useEffect, useState } from "react";

import { listNotifications } from "../src/notifications";

/**
 * How many messages are unread, in the header, on every screen.
 *
 * M11 Screens, slice 2. **A separate file from the admin bell, and importing this app's own data
 * module.** `UI-ISO-001` is about neither bundle containing the other's endpoint paths, and the two
 * `notifications.ts` modules were split for that reason in slice 1 — a shared bell would import one
 * of them and undo the split in the component that renders on every single page.
 *
 * The count is the server's `unread_count`, read once per mount and not polled. §2.3 `:205`, and
 * the admin bell's docstring carries the longer form of both arguments.
 *
 * **A trader's notification is often the only place a failure appears.** M9 decided that a failed
 * payment reaches its trader as a notification rather than as a publication, so for this audience
 * the bell is the difference between finding that out and not.
 */
export function NotificationBell() {
  const [unread, setUnread] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listNotifications(null, controller.signal)
      .then((page) => setUnread(page.unread_count))
      .catch(() => {
        if (!controller.signal.aborted) setUnread(null);
      });
    return () => controller.abort();
  }, []);

  return (
    <Link
      aria-label={
        unread === null
          ? t("notifications.nav")
          : `${t("notifications.nav")} — ${t("notifications.unreadCount")}: ${unread}`
      }
      className="flex items-center gap-1"
      href="/notifications"
    >
      <Icon name="notifications" />
      {unread !== null && unread > 0 ? (
        <span
          aria-hidden="true"
          className="rounded-full bg-[var(--gold-500)] px-2 text-xs font-bold"
        >
          {unread}
        </span>
      ) : null}
    </Link>
  );
}
