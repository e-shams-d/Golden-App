"use client";

import { t } from "@gold/localization";
import Link from "next/link";
import { useEffect, useState } from "react";

import { loadTraderSession, type TraderSession } from "../src/session";

/**
 * The way in. Until this existed there was none.
 *
 * A goldsmith arriving at `trader.localhost` met a shell describing the platform and a
 * bottom navigation whose five items were the home page, three routes that did not exist,
 * and an account screen that redirects when signed out. **No link to `/login` and no link
 * to `/register`** — the two things a person arriving here needs — so the only way in was
 * to know the URL. Found by somebody trying to use the application rather than by any test,
 * which is the honest description of how this class of defect gets found.
 *
 * Signed out it offers both doors; signed in it points at the account screen, which is
 * where the centre's decision appears. The distinction is drawn from `GET /auth/me` on
 * every mount rather than from anything cached, because a session revoked a minute ago must
 * stop looking signed in now.
 */
export function EntryPanel() {
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

  if (session.kind === "loading") {
    return (
      <section
        className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"
        role="status"
      >
        <p className="text-[var(--ink-600)]">{t("trader.entry.loading")}</p>
      </section>
    );
  }

  if (session.kind === "signed-in") {
    return (
      <section className="mt-6 rounded-2xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-5">
        <h2 className="text-xl font-black">{t("trader.entry.signedInTitle")}</h2>
        <p className="mt-2 leading-8 text-[var(--ink-600)]">{t("trader.entry.signedInBody")}</p>
        <Link
          className="mt-4 inline-block rounded-lg bg-[var(--ink-950)] px-5 py-3 font-bold text-white"
          href="/profile"
        >
          {t("trader.entry.openAccount")}
        </Link>
      </section>
    );
  }

  return (
    <section className="mt-6 rounded-2xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-5">
      <h2 className="text-xl font-black">{t("trader.entry.anonymousTitle")}</h2>
      <p className="mt-2 leading-8 text-[var(--ink-600)]">{t("trader.entry.anonymousBody")}</p>
      {/* Both doors, and registration is the wider one on purpose: a goldsmith meeting this
          screen for the first time has no account, and the platform's only unauthenticated
          write is the one that gives them one. */}
      <div className="mt-4 flex flex-wrap gap-3">
        <Link
          className="rounded-lg bg-[var(--ink-950)] px-5 py-3 font-bold text-white"
          href="/register"
        >
          {t("trader.entry.register")}
        </Link>
        <Link
          className="rounded-lg border border-[var(--ink-950)] px-5 py-3 font-bold"
          href="/login"
        >
          {t("trader.entry.signIn")}
        </Link>
      </div>
    </section>
  );
}
