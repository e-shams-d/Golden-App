"use client";

import { t } from "@gold/localization";
import { ApplicationShell, visibleNavigation } from "@gold/ui";
import { useEffect, useState, type ReactNode } from "react";

import { adminNavigation } from "../src/navigation";
import { loadAdminSession, type AdminSession } from "../src/session";
import { SignOutButton } from "./sign-out-button";

/**
 * The shell, and the first thing in this app that differs by who is looking at it.
 *
 * Until slice 10D it rendered a literal `admin.roleUnknown` and every navigation item
 * unconditionally, so an authenticated administrator and an anonymous visitor produced
 * identical bytes. Two obligations were owed against that.
 *
 * **Anonymous sees the navigation with no gated items**, not an empty sidebar and not the
 * full one. Every item carrying a permission disappears; the dashboard, which carries none,
 * stays. That is the honest rendering of "we do not know who you are" and it is also what
 * makes the difference assertable — an empty nav would be indistinguishable from a failed
 * load.
 *
 * **While loading, nothing gated is shown.** Showing the full navigation and then removing
 * items is worse than showing fewer and adding them: the first flashes screens a person
 * cannot reach and invites a click that will be refused.
 *
 * The permissions come from `GET /auth/me` on every mount rather than from anything cached.
 * A role revoked a minute ago must stop showing its screens now, and the server resolves
 * grants per request for the same reason.
 */
export function AdminShell({ children }: Readonly<{ children: ReactNode }>) {
  const [session, setSession] = useState<AdminSession>({ kind: "loading" });

  // State is set from the promise's callback rather than after an await in the effect body:
  // `react-hooks/set-state-in-effect` refuses the second shape. The abort is the other half
  // — leaving the page mid-request must not set state on a component that is gone.
  useEffect(() => {
    const controller = new AbortController();
    loadAdminSession(controller.signal)
      .then((loaded) => setSession(loaded))
      .catch(() => {
        if (!controller.signal.aborted) setSession({ kind: "anonymous" });
      });
    return () => controller.abort();
  }, []);

  const permissions = session.kind === "signed-in" ? session.permissions : [];

  return (
    <ApplicationShell
      appName={t("admin.appName")}
      headerContext={
        <div className="flex items-center gap-4">
          <span>{headerFor(session)}</span>
          {/* Only when there is a session to end. Offering sign-out to an anonymous visitor
              would be a button that either does nothing or logs a 401 — and on this shell
              the header is the only place a person looks for it. */}
          {session.kind === "signed-in" ? <SignOutButton /> : null}
        </div>
      }
      navigation={visibleNavigation(adminNavigation, permissions)}
      navigationLabel="ناوبری عملیات داخلی"
      skipToContentLabel={t("common.skipToContent")}
      variant="admin"
    >
      {children}
    </ApplicationShell>
  );
}

/**
 * What the header says about the current session.
 *
 * The subject id rather than a name, because `/auth/me` returns no display name — the
 * adapter sets `displayName` to the id and says so. Rendering the id is honest; inventing a
 * name from it would not be, and inventing a *role* from the permission list would be worse:
 * the same permissions can arrive from more than one role and the server never says which.
 */
function headerFor(session: AdminSession): string {
  if (session.kind === "loading") return t("admin.session.loading");
  if (session.kind === "anonymous") return t("admin.session.anonymous");
  return t("admin.session.signedIn").replace("{id}", session.subjectId);
}
