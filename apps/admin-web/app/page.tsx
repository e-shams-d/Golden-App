import { t } from "@gold/localization";
import Link from "next/link";

import { AdminShell } from "../components/admin-shell";
import { QueueIndexPanel } from "../components/queue-index";
import { SessionPanel } from "../components/session-panel";

export default function AdminHomePage() {
  return (
    <AdminShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <p className="text-sm font-bold text-[var(--gold-700)]">{t("foundation.title")}</p>
        <h1 className="mt-2 text-3xl font-black">{t("admin.shellTitle")}</h1>
        <p className="mt-4 max-w-3xl leading-8 text-[var(--ink-600)]">
          {t("admin.shellDescription")}
        </p>
        <p className="mt-5 rounded-xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-4 leading-7">
          {t("foundation.noAuthority")}
        </p>
      </section>

      {/* The one part of this page that differs by session, and the only thing
          `UI-LOGIN-001` has to assert against. Everything above and below renders
          identically for an administrator and a stranger. */}
      <SessionPanel />

      <section aria-labelledby="queue-heading" className="mt-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-black" id="queue-heading">
              {t("admin.queueTitle")}
            </h2>
            <p className="mt-2 max-w-3xl leading-7 text-[var(--ink-600)]">
              {t("admin.queueDescription")}
            </p>
          </div>
          <Link
            className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 font-bold"
            href="/states/empty"
          >
            {t("foundation.openStates")}
          </Link>
        </div>
        {/*
          M11 Screens slice 2. Four invented queue names and an em dash stood here for eleven
          milestones, with a screen-reader note saying the count had not been received. That was
          honest then and false now: sixteen queues have routes, the counts are the server's, and
          none of the four names was one §19.2 gives.

          **This is the dashboard and the queue landing page both**, rather than a new `/queues`
          index screen. The dashboard is already where an authenticated person arrives and is
          already the one navigation item that carries no permission, so a second landing surface
          would be two pages competing to be the place work is found.
        */}
        <QueueIndexPanel />
      </section>
    </AdminShell>
  );
}
