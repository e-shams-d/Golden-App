"use client";

import { t } from "@gold/localization";
import { Icon } from "@gold/ui";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminAuthAdapter } from "../src/auth";

/**
 * The way out. There was none.
 *
 * `adminAuthAdapter.logout` has existed since slice 9 — a complete `POST /auth/logout`
 * call — and was **imported nowhere**, like `loadSession` before slice 10D. So a signed-in
 * administrator had no way to become signed-out except by clearing cookies by hand, and
 * the one thing a demonstration most needs to show — that two roles see different menus —
 * could not be shown without two browsers.
 *
 * That is the fourth complete mechanism in this milestone found with no caller, after the
 * security stamp, the step-up context store and the session adapters.
 *
 * **`router.refresh()` after `replace`, in that order.** The session is an HTTP-only
 * cookie; the server can now answer as an anonymous caller, and only a refresh makes that
 * visible. Replacing without refreshing leaves the shell rendering the permissions of the
 * person who just left — which on a shared machine is the wrong thing to leave on screen.
 *
 * **A failed logout still navigates.** If the request fails the browser has no way to know
 * whether the session was revoked, and leaving somebody on an authenticated-looking screen
 * after they pressed sign-out is the worse of the two mistakes.
 */
export function SignOutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function signOut() {
    if (busy) return;
    setBusy(true);
    try {
      await adminAuthAdapter.logout();
    } catch {
      // Deliberately swallowed; see the docstring.
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <button
      className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 font-bold disabled:opacity-60"
      disabled={busy}
      onClick={() => void signOut()}
      type="button"
    >
      <Icon name="logout" size={18} />
      <span>{busy ? t("common.signingOut") : t("common.signOut")}</span>
    </button>
  );
}
