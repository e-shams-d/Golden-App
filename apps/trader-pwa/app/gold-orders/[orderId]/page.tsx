"use client";

import { t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { TraderShell } from "../../../components/trader-shell";
import { readOrder, submitOrder, type GoldOrder } from "../../../src/gold-orders";

/**
 * One gold order as its owner sees it, and the one command they may issue.
 * §9.12, §17.1 (`15_Agent_Implementation_Plan.md:1931`).
 *
 * M11 Screens, slice 5.
 *
 * **`If-Match` is the ETag this page rendered, echoed.** `GET /gold-sale-orders/{id}` did not
 * issue one until this slice — it returned `record_version` in the body and no header — so submit
 * had no server-given precondition to compare against.
 *
 * **The submit control is offered on the order's own status**, not on `allowed_actions`: that
 * projection covers payment requests and there is no gold equivalent. Recorded rather than left
 * as a difference somebody has to notice — and the server refuses regardless, §20.1.
 *
 * A second trader gets 404 rather than 403 on someone else's order, which
 * `test_gold_sale_orders.py` has asserted since M10; this screen renders that as "not found"
 * because it cannot tell the two apart and should not try.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly order: GoldOrder; readonly ifMatch: string }
  | { readonly kind: "failed" };

/** The one status from which a trader may hand the order over. `06_Workflows` §8.1. */
const SUBMITTABLE = "draft";

export default function TraderGoldOrderPage() {
  const parameters = useParams<{ orderId: string }>();
  const orderId = typeof parameters.orderId === "string" ? parameters.orderId : "";

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal): Promise<Phase> => {
      const { order, ifMatch } = await readOrder(orderId, signal);
      return { kind: "ready", order, ifMatch };
    },
    [orderId],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((next) => setPhase(next))
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, [load]);

  const hand_over = async (ifMatch: string) => {
    setBusy(true);
    setNotice(null);
    try {
      await submitOrder(orderId, ifMatch);
      setPhase(await load());
    } catch (error) {
      // 412 here means the centre moved the order while this person was reading — the exact event
      // the precondition exists for, and worth its own sentence.
      const status = (error as { status?: number }).status;
      setNotice(status === 412 ? t("gold.stale") : t("gold.refused"));
      try {
        setPhase(await load());
      } catch {
        setPhase({ kind: "failed" });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <TraderShell>
      <section aria-labelledby="order-heading" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-xl font-semibold" id="order-heading">
            {t("gold.detailTitle")}
          </h1>
          <Link className="rounded border px-3 py-1 text-sm" href="/gold-orders">
            {t("gold.backToList")}
          </Link>
        </div>

        {phase.kind === "loading" ? (
          <StateView
            description={t("state.loading.description")}
            headingLevel={2}
            kind="loading"
            title={t("state.loading.title")}
          />
        ) : null}

        {phase.kind === "failed" ? (
          <StateView
            description={t("gold.detailFailed")}
            headingLevel={2}
            kind="error"
            title={t("gold.detailFailedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            <dl className="grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-sm font-medium">{t("gold.orderNumber")}</dt>
                <dd>
                  <BidiText>{phase.order.order_number}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("gold.status")}</dt>
                <dd>
                  <BidiText>{phase.order.status}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("gold.type")}</dt>
                <dd>
                  <BidiText>{phase.order.gold_type}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("gold.weight")}</dt>
                <dd>
                  <BidiText>
                    {phase.order.gold_weight} {phase.order.weight_unit}
                  </BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("gold.purity")}</dt>
                <dd>
                  <BidiText>{phase.order.gold_purity}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("gold.expectedAmount")}</dt>
                <dd>
                  {phase.order.expected_amount_irr === null ? (
                    <span>{t("gold.notPricedYet")}</span>
                  ) : (
                    <BidiText>{phase.order.expected_amount_irr}</BidiText>
                  )}
                </dd>
              </div>
              {phase.order.final_amount_irr !== null ? (
                <div>
                  <dt className="text-sm font-medium">{t("gold.finalAmount")}</dt>
                  <dd>
                    <BidiText>{phase.order.final_amount_irr}</BidiText>
                  </dd>
                </div>
              ) : null}
            </dl>

            {notice !== null ? (
              <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
                {notice}
              </p>
            ) : null}

            {/* Absent, not disabled, once the order has been handed over: there is nothing a
                trader can do to make a submitted order submittable again. */}
            {phase.order.status === SUBMITTABLE ? (
              <div className="space-y-2">
                <p className="text-sm">{t("gold.submitExplains")}</p>
                <button
                  className="rounded border px-3 py-1 font-bold"
                  disabled={busy}
                  onClick={() => hand_over(phase.ifMatch)}
                  type="button"
                >
                  {t("gold.submit")}
                </button>
              </div>
            ) : null}
          </>
        ) : null}
      </section>
    </TraderShell>
  );
}
