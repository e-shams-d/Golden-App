"use client";

import { t } from "@gold/localization";
import Link from "next/link";
import { useEffect, useState } from "react";

import { loadAdminSession, type AdminSession } from "../src/session";

/**
 * The part of the landing page that an anonymous visitor does not render.
 *
 * `UI-LOGIN-001` asks that signing in lands somebody on a surface that differs by session,
 * and until slice 10D there was nothing to assert against: both login handlers finished
 * with `router.replace("/")`, and `/` was a static shell producing identical bytes for an
 * administrator and a stranger.
 *
 * **What differs is a heading, not a styling detail.** The test asserts a level-two heading
 * that exists in one case and not the other, because an assertion on a class name or a
 * colour would pass over a page that told the person nothing.
 *
 * **The permission count is shown and the permission names are not.** The count is enough
 * to make the surface session-derived and to tell somebody their access is not empty;
 * listing the codes would put the deployment's authorisation vocabulary on a screen, which
 * is a map an attacker who has stolen one session would rather have than not.
 *
 * A separate component from `AdminShell` on purpose: the shell is on every page and this is
 * the landing page's own content. Folding it in would have made every screen re-render the
 * session panel, and the assertion "this is what you land on" would have been true of
 * everywhere.
 */
export function SessionPanel() {
  const [session, setSession] = useState<AdminSession>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    loadAdminSession(controller.signal)
      .then((loaded) => setSession(loaded))
      .catch(() => {
        if (!controller.signal.aborted) setSession({ kind: "anonymous" });
      });
    return () => controller.abort();
  }, []);

  if (session.kind === "loading") {
    return (
      <section className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5" role="status">
        <p className="text-[var(--ink-600)]">{t("admin.session.loading")}</p>
      </section>
    );
  }

  if (session.kind === "anonymous") {
    return (
      <section className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <h2 className="text-xl font-black">{t("admin.landing.anonymousTitle")}</h2>
        <p className="mt-2 leading-8 text-[var(--ink-600)]">{t("admin.landing.anonymousBody")}</p>
        <Link
          className="mt-4 inline-block rounded-lg bg-[var(--ink-950)] px-4 py-3 font-bold text-white"
          href="/login"
        >
          {t("admin.landing.signIn")}
        </Link>
      </section>
    );
  }

  return (
    <section className="mt-6 rounded-2xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-5">
      <h2 className="text-xl font-black">{t("admin.landing.signedInTitle")}</h2>
      <p className="mt-2 leading-8 text-[var(--ink-600)]">{t("admin.landing.signedInBody")}</p>
      <p className="mt-3 font-bold">
        {t("admin.landing.permissionCount").replace("{count}", String(session.permissions.length))}
      </p>
    </section>
  );
}
