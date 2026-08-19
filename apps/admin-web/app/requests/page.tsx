"use client";

import { paymentRequestStatusLabel, t, toPersianDigits } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../components/admin-shell";
import { listRequests, type RequestListing } from "../../src/payment-requests";

/**
 * The accountant's queue. Before slice 8 there was no way to learn what was waiting.
 *
 * **The default view is what needs the centre, not everything.** `submitted_to_center` is
 * where work arrives, so that is the filter the screen opens with — a queue that opened on
 * every status would put cancelled and already-eligible requests in front of somebody looking
 * for the next thing to review. The other filters are there because a reviewer also needs to
 * find what they returned and what they have finished.
 *
 * **The status filter is the server's, not a client-side `.filter()`.** The request goes back
 * with `?status=`, so the screen shows a page of the queue rather than a page of whatever
 * happened to be in the first response — which is the difference that matters the day the
 * centre has more requests than one response carries.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly items: readonly RequestListing[] }
  | { readonly kind: "forbidden" }
  | { readonly kind: "failed" };

const FILTERS = [
  "submitted_to_center",
  "under_accountant_review",
  "needs_trader_correction",
  "eligible_for_batching",
  "",
] as const;

export default function AdminRequestsPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [status, setStatus] = useState<string>("submitted_to_center");

  // A 403 is a different screen from a 500: one says "not for you", the other says "try
  // again". Rendering the same panel for both sends an operator to fix a network they cannot.
  const phaseForError = (error: unknown): Phase =>
    (error as { status?: number }).status === 403 ? { kind: "forbidden" } : { kind: "failed" };

  const load = useCallback(
    (next: string, signal?: AbortSignal) =>
      listRequests(next || undefined, signal)
        .then((items) => setPhase({ kind: "ready", items }))
        .catch((error: unknown) => {
          if (!signal?.aborted) setPhase(phaseForError(error));
        }),
    [],
  );

  // The effect subscribes and nothing more. `react-hooks/set-state-in-effect` refuses a
  // synchronous `setPhase` here and is right to — an effect that sets state on the way in can
  // cascade renders. So the loading state is set where the filter actually changes, by the
  // handler below, and the first render already starts in it.
  useEffect(() => {
    const controller = new AbortController();
    void load(status, controller.signal);
    return () => controller.abort();
  }, [load, status]);

  const choose = (value: string) => {
    if (value === status) return;
    setPhase({ kind: "loading" });
    setStatus(value);
  };

  return (
    <AdminShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("admin.requests.title")}</h1>
        <p className="mt-3 max-w-3xl leading-8 text-[var(--ink-600)]">
          {t("admin.requests.description")}
        </p>

        <div className="mt-5 flex flex-wrap gap-2">
          {FILTERS.map((value) => (
            <button
              aria-pressed={status === value}
              className={`rounded-full border px-4 py-2 font-bold ${
                status === value
                  ? "border-[var(--gold-700)] bg-[var(--gold-700)] text-white"
                  : "border-[var(--border)]"
              }`}
              key={value || "all"}
              onClick={() => choose(value)}
              type="button"
            >
              {value ? paymentRequestStatusLabel(value) : t("admin.requests.filterAll")}
            </button>
          ))}
        </div>

        <div className="mt-6">
          {phase.kind === "loading" ? (
            <StateView
              headingLevel={2}
              description={t("admin.requests.loading")}
              kind="loading"
              title={t("admin.requests.loading")}
            />
          ) : null}

          {phase.kind === "forbidden" ? (
            <StateView
              headingLevel={2}
              description={t("admin.requests.forbidden")}
              kind="forbidden"
              title={t("admin.requests.forbiddenTitle")}
            />
          ) : null}

          {phase.kind === "failed" ? (
            <StateView
              headingLevel={2}
              actions={
                <button
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-2 font-bold"
                  onClick={() => void load(status)}
                  type="button"
                >
                  {t("common.refresh")}
                </button>
              }
              description={t("admin.requests.failed")}
              kind="error"
              title={t("admin.requests.failedTitle")}
            />
          ) : null}

          {phase.kind === "ready" && phase.items.length === 0 ? (
            <StateView
              headingLevel={2}
              description={t("admin.requests.empty")}
              kind="empty"
              title={t("admin.requests.emptyTitle")}
            />
          ) : null}

          {phase.kind === "ready" && phase.items.length > 0 ? (
            <table className="w-full border-collapse text-start">
              <caption className="sr-only">{t("admin.requests.title")}</caption>
              <thead>
                <tr className="border-b border-[var(--border)] text-sm text-[var(--ink-600)]">
                  <th className="p-3 text-start" scope="col">
                    {t("admin.requests.title")}
                  </th>
                  <th className="p-3 text-start" scope="col">
                    {t("trader.requests.beneficiary")}
                  </th>
                  <th className="p-3 text-start" scope="col">
                    {t("trader.requests.amount")}
                  </th>
                  <th className="p-3 text-start" scope="col">
                    {t("trader.request.status")}
                  </th>
                  <th className="p-3 text-start" scope="col">
                    {t("admin.traders.actions")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {phase.items.map(({ request, current_revision: revision }) => (
                  <tr className="border-b border-[var(--border)] align-top" key={request.id}>
                    {/* Latin-digit identifier in a right-to-left table: isolated so its
                        parts do not reorder into a different number. */}
                    <td className="p-3 font-mono font-bold" dir="ltr">
                      {request.request_number}
                    </td>
                    <td className="p-3">{revision?.beneficiary_name_snapshot ?? "—"}</td>
                    <td className="p-3" dir="ltr">
                      {revision
                        ? revision.entered_amount
                          ? `${toPersianDigits(revision.entered_amount.value)} ${
                              revision.entered_amount.unit === "TOMAN"
                                ? t("money.unit.TOMAN")
                                : t("money.unit.IRR")
                            }`
                          : `${toPersianDigits(revision.amount_irr)} ${t("money.unit.IRR")}`
                        : "—"}
                    </td>
                    <td className="p-3">{paymentRequestStatusLabel(request.status)}</td>
                    <td className="p-3">
                      <Link
                        className="font-bold text-[var(--gold-700)] underline"
                        href={`/requests/${request.id}`}
                      >
                        {t("admin.requests.open")}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      </section>
    </AdminShell>
  );
}
