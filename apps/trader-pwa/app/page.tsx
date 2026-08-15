import { t } from "@gold/localization";
import Link from "next/link";

import { EntryPanel } from "../components/entry-panel";
import { TraderShell } from "../components/trader-shell";

const foundationCards = [
  {
    title: t("foundation.statesTitle"),
    description: t("foundation.statesDescription"),
  },
  {
    title: t("foundation.apiTitle"),
    description: t("foundation.apiDescription"),
  },
  {
    title: t("foundation.securityTitle"),
    description: t("foundation.securityDescription"),
  },
] as const;

export default function TraderHomePage() {
  return (
    <TraderShell>
      <section className="rounded-3xl bg-[var(--ink-950)] p-6 text-white shadow-[var(--shadow-raised)] sm:p-8">
        <p className="text-sm font-bold text-[var(--gold-100)]">{t("trader.welcome")}</p>
        <h1 className="mt-2 text-3xl font-black leading-tight">{t("trader.shellTitle")}</h1>
        <p className="mt-4 max-w-prose leading-8 text-white/85">{t("trader.shellDescription")}</p>
      </section>

      {/* Immediately under the banner, because it is the only thing on this page a person
          arriving at the application needs. Everything below is M1 scaffolding describing
          what the shell is, which is interesting to a reviewer and useless to a goldsmith. */}
      <EntryPanel />

      <section aria-labelledby="foundation-heading" className="mt-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-black" id="foundation-heading">
              {t("foundation.title")}
            </h2>
            <p className="mt-2 text-[var(--ink-600)]">{t("trader.noData")}</p>
          </div>
          <Link
            className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 font-bold"
            href="/states/empty"
          >
            {t("foundation.openStates")}
          </Link>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {foundationCards.map((card) => (
            <article
              className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"
              key={card.title}
            >
              <h3 className="font-black">{card.title}</h3>
              <p className="mt-2 leading-7 text-[var(--ink-600)]">{card.description}</p>
            </article>
          ))}
        </div>
        <p className="mt-6 rounded-xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-4 leading-7">
          {t("foundation.noAuthority")}
        </p>
      </section>
    </TraderShell>
  );
}
