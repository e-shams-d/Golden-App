"use client";

import { t } from "@gold/localization";
import { ApplicationShell, visibleNavigation } from "@gold/ui";
import { useEffect, useState, type ReactNode } from "react";

import { adminNavigation } from "../src/navigation";
import { loadAdminSession, type AdminSession } from "../src/session";
import { NotificationBell } from "./notification-bell";
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
          {session.kind === "signed-in" ? (
            <>
              {/* M11 Screens slice 2, the bell slice 1 recorded as owed — and it needed no change
                  to `ApplicationShell` after all: `headerContext` was already the slot for it.
                  Gated on the session for the same reason sign-out is: an anonymous visitor's
                  count request answers 401, so the bell would be an ornament that can only fail.
                  The `/notifications` navigation item stays visible to everybody, which is
                  §20.1's point — visibility is not authorization — but a *count* implies there is
                  something to count. */}
              <NotificationBell />
              <SignOutButton />
            </>
          ) : null}
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
 * **Both halves of the old note have been overtaken, and one of them was wrong.**
 *
 * It said the id was shown "because `/auth/me` returns no display name". True, and the
 * gap was in the contract rather than here: both `AdminUser` and `TraderUser` carry
 * `full_name` as a non-null column, and it had never left the database. `ActorSummary`
 * carries it now.
 *
 * It also said that inventing a role from the permission list would be worse because
 * "the server never says which". The server does say which — `ActorSummary.roles` has
 * always been in the response, and this app's adapter dropped it before the shell could
 * see it. The claim was true of the data arriving and false of the contract, which is the
 * more misleading of the two.
 *
 * The id remains the fallback when the server sends no name, because that is still the
 * honest answer rather than a blank.
 */
function headerFor(session: AdminSession): string {
  if (session.kind === "loading") return t("admin.session.loading");
  if (session.kind === "anonymous") return t("admin.session.anonymous");

  const who = session.displayName.trim().length > 0 ? session.displayName : session.subjectId;
  // One role or none. A reader needs to know which hat they are wearing, and the catalogue
  // grants admins exactly one role today; listing several would be inventing a shape the
  // seeded data does not have.
  //
  // The code as the server sends it, which is what `/roles` prints too. There is no
  // Persian name for a role anywhere in the catalogue, and inventing one here would give
  // the header and the roles screen two different words for the same thing — the drift
  // `paymentRequestStatusLabel` warns about. A role vocabulary is worth having and
  // belongs in one place serving both, not arriving sideways through a header.
  const [role] = session.roles;
  return role === undefined
    ? t("admin.session.signedIn").replace("{id}", who)
    : t("admin.session.signedInAs").replace("{id}", who).replace("{role}", role);
}
