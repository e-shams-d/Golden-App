import { t } from "@gold/localization";
import Link from "next/link";

import { AdminShell } from "../components/admin-shell";

const queueCards = [
  t("admin.queue.traderApproval"),
  t("admin.queue.requestReview"),
  t("admin.queue.managerApproval"),
  t("admin.queue.bankResult"),
] as const;

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
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {queueCards.map((title) => (
            <article
              className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"
              key={title}
            >
              <h3 className="font-black">{title}</h3>
              <p className="mt-4 text-3xl font-black">
                <span aria-hidden="true">—</span>
                <span className="sr-only">تعداد هنوز دریافت نشده است</span>
              </p>
            </article>
          ))}
        </div>
      </section>
    </AdminShell>
  );
}
