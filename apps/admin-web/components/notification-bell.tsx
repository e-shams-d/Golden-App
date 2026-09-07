"use client";

import { t } from "@gold/localization";
import { Icon } from "@gold/ui";
import Link from "next/link";
import { useEffect, useState } from "react";

import { listNotifications } from "../src/notifications";

/**
 * How many messages are unread, in the header, on every screen.
 *
 * M11 Screens, slice 2, and the half slice 1 recorded as owed. **It goes in `headerContext` rather
 * than in `ApplicationShell`** — the shared shell already exposes that slot, so the bell needed no
 * change to a component both applications render. Slice 1 deferred it on the assumption that it
 * would; that assumption was wrong and the slot was there all along.
 *
 * **The count is the server's `unread_count`.** Never `items.filter(unread).length`: the list is
 * paginated, so a derived count is wrong as soon as there is more than one page — the ordinary
 * case, not an edge one. §2.3 `:205`.
 *
 * **Read once per mount, and deliberately not polled.** A number that refreshes itself every few
 * seconds is a promise that it is live, and this one is not: nothing pushes to this client. Read on
 * navigation is honest about that, and marking a message read re-reads it because the notifications
 * page reloads on the same mount.
 *
 * **Silent on failure.** A header ornament that renders «دریافت نشد» on every page would turn one
 * failed request into a permanent alarm about something nobody can act on from here. The
 * notifications page reports its own failure, which is where a person went to read them.
 */
export function NotificationBell() {
  const [unread, setUnread] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listNotifications(null, controller.signal)
      .then((page) => setUnread(page.unread_count))
      .catch(() => {
        // Anonymous visitors get a 401 here, which is not a failure worth reporting: the header
        // already says there is no session.
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
      {/* Rendered only when there is something unread. A visible zero is a badge that draws the
          eye to the absence of news. `null` — not yet known, or no session — shows nothing at all
          rather than a zero that would be a claim. */}
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
