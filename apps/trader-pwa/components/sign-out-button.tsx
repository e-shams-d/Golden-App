"use client";

import { t } from "@gold/localization";
import { Icon } from "@gold/ui";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { traderAuthAdapter } from "../src/auth";

/**
 * The trader app's way out.
 *
 * Per-app rather than shared with the admin one, for the reason every module in this
 * bundle repeats: `UI-ISO-001` requires that neither bundle name the other's endpoint
 * paths, and a shared button importing both adapters would put the admin logout route into
 * this bundle's JavaScript.
 *
 * Redirects to `/` rather than `/login`, unlike the centre's. A goldsmith who signs out has
 * somewhere public to be — the entry screen with its two doors — while an administrator
 * signed out of an internal tool has nothing to look at but the sign-in form.
 */
export function SignOutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function signOut() {
    if (busy) return;
    setBusy(true);
    try {
      await traderAuthAdapter.logout();
    } catch {
      // A failed logout still navigates: the browser cannot tell whether the session was
      // revoked, and leaving somebody on an authenticated-looking screen after they
      // pressed sign-out is the worse of the two mistakes.
    } finally {
      router.replace("/");
      router.refresh();
    }
  }

  return (
    <button
      className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm font-bold disabled:opacity-60"
      disabled={busy}
      onClick={() => void signOut()}
      type="button"
    >
      <Icon name="logout" size={18} />
      <span>{busy ? t("common.signingOut") : t("common.signOut")}</span>
    </button>
  );
}
