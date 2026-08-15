"use client";

import { t } from "@gold/localization";
import { ApplicationShell } from "@gold/ui";
import { useEffect, useState, type ReactNode } from "react";

import { traderNavigation } from "../src/navigation";
import { loadTraderSession, type TraderSession } from "../src/session";
import { SignOutButton } from "./sign-out-button";

/**
 * The trader shell, which now knows whether anybody is signed in.
 *
 * It was a server component rendering a fixed header. That was fine while nothing depended
 * on the session and wrong the moment a goldsmith needed to sign out: there was no control
 * anywhere in the application, so switching accounts meant clearing cookies by hand.
 *
 * The session is read here rather than passed down because the header is the only place a
 * person looks for a way out, and the header lives in the shell. The cost is that every
 * page now makes one `GET /auth/me` — the same cost the admin shell already pays, and the
 * same reason: a session revoked a minute ago must stop looking signed in now.
 */
export function TraderShell({ children }: Readonly<{ children: ReactNode }>) {
  const [session, setSession] = useState<TraderSession>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    loadTraderSession(controller.signal)
      .then((loaded) => setSession(loaded))
      .catch(() => {
        if (!controller.signal.aborted) setSession({ kind: "anonymous" });
      });
    return () => controller.abort();
  }, []);

  return (
    <ApplicationShell
      appName={t("trader.appName")}
      // Only when there is a session to end. An anonymous visitor offered "sign out" would
      // press a button that either does nothing or logs a 401.
      headerContext={session.kind === "signed-in" ? <SignOutButton /> : null}
      navigation={traderNavigation}
      navigationLabel="ناوبری اصلی طلافروش"
      skipToContentLabel={t("common.skipToContent")}
      variant="trader"
    >
      {children}
    </ApplicationShell>
  );
}
