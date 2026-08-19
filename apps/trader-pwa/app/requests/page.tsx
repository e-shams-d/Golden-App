"use client";

import { paymentRequestStatusLabel, t, toPersianDigits } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";
import { useEffect, useState } from "react";

import { TraderShell } from "../../components/trader-shell";
import { listRequests, type RequestListing } from "../../src/payment-requests";
import { amountForDisplay, correctionNotice } from "../../src/request-view";

/**
 * The trader's own requests. Until slice 8 this route was a navigation item with no page,
 * and before that the API had nothing to list — eleven published operations on the aggregate
 * and only one of them read.
 *
 * **A returned request is the one thing this screen must not bury.** It is the only state
 * where the trader has to act, so it is sorted to nothing and highlighted instead: the row
 * carries the accountant's note, and the link says "correct" rather than "view". A list that
 * showed `needs_trader_correction` as one status among six would be a list where the work
 * waiting on them is indistinguishable from the work waiting on somebody else.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly items: readonly RequestListing[] }
  | { readonly kind: "failed" };

const NEEDS_CORRECTION = "needs_trader_correction";

export default function TraderRequestsPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    listRequests(undefined, controller.signal)
      .then((items) => setPhase({ kind: "ready", items }))
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, []);

  return (
    <TraderShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-3xl font-black">{t("trader.requests.title")}</h1>
          <Link
            className="rounded-lg bg-[var(--gold-700)] px-4 py-2 font-bold text-white"
            href="/requests/new"
          >
            {t("trader.requests.new")}
          </Link>
        </div>
        <p className="mt-3 max-w-3xl leading-8 text-[var(--ink-600)]">
          {t("trader.requests.description")}
        </p>

        <div className="mt-6">
          {phase.kind === "loading" ? (
            <StateView
              headingLevel={2}
              description={t("trader.requests.loading")}
              kind="loading"
              title={t("trader.requests.loading")}
            />
          ) : null}

          {phase.kind === "failed" ? (
            <StateView
              headingLevel={2}
              description={t("trader.requests.failed")}
              kind="error"
              title={t("trader.requests.failedTitle")}
            />
          ) : null}

          {phase.kind === "ready" && phase.items.length === 0 ? (
            <StateView
              headingLevel={2}
              description={t("trader.requests.empty")}
              kind="empty"
              title={t("trader.requests.emptyTitle")}
            />
          ) : null}

          {phase.kind === "ready" && phase.items.length > 0 ? (
            <ul className="mt-2 flex flex-col gap-4">
              {phase.items.map(({ request, current_revision: revision }) => {
                const waiting = request.status === NEEDS_CORRECTION;
                const note = correctionNotice(request);
                const amount = revision ? amountForDisplay(revision) : null;
                return (
                  <li
                    className={`rounded-2xl border p-5 ${
                      waiting
                        ? "border-[var(--gold-500)] bg-[var(--gold-50)]"
                        : "border-[var(--border)]"
                    }`}
                    key={request.id}
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-3">
                      {/* The request number is a Latin-digit identifier in a right-to-left
                          page. Without `dir="ltr"` its parts render in the wrong order and
                          it reads as a different number. */}
                      <span className="font-mono font-bold" dir="ltr">
                        {request.request_number}
                      </span>
                      <span className="rounded-full border border-[var(--border)] px-3 py-1 text-sm">
                        {paymentRequestStatusLabel(request.status)}
                      </span>
                    </div>

                    {revision && amount ? (
                      <dl className="mt-4 grid gap-3 sm:grid-cols-2">
                        <div>
                          <dt className="text-sm text-[var(--ink-600)]">
                            {t("trader.requests.beneficiary")}
                          </dt>
                          <dd className="font-bold">{revision.beneficiary_name_snapshot}</dd>
                        </div>
                        <div>
                          <dt className="text-sm text-[var(--ink-600)]">
                            {t("trader.requests.amount")}
                          </dt>
                          {/* Persian digits for a quantity a person reads, and the unit
                              beside it. `amountForDisplay` chose which pair to show and did
                              no arithmetic; this only renders it. */}
                          <dd className="font-bold" dir="ltr">
                            {toPersianDigits(amount.value)} {unitLabel(amount.unit)}
                          </dd>
                        </div>
                      </dl>
                    ) : null}

                    {note ? (
                      <p className="mt-4 rounded-xl border border-[var(--gold-500)] bg-[var(--surface)] p-4 leading-7">
                        <span className="font-bold">{t("trader.requests.reviewNote")}: </span>
                        {note}
                      </p>
                    ) : null}

                    <div className="mt-4">
                      <Link
                        className="font-bold text-[var(--gold-700)] underline"
                        href={`/requests/${request.id}`}
                      >
                        {waiting ? t("trader.requests.correct") : t("trader.requests.open")}
                      </Link>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      </section>
    </TraderShell>
  );
}

/** The unit as a word, so `TOMAN` never reaches a person's eyes as a code. */
function unitLabel(unit: string): string {
  return unit === "TOMAN" ? t("money.unit.TOMAN") : t("money.unit.IRR");
}
