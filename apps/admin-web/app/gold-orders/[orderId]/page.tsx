"use client";

import { t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../components/admin-shell";
import {
  createPricingVersion,
  readOrder,
  type GoldOrder,
  type PricingVersion,
} from "../../../src/gold-orders";

/**
 * The pricing workspace. §17.2 (`15_Agent_Implementation_Plan.md:1944`).
 *
 * M11 Screens, slice 5. M10 built the pricing command and nothing has ever priced an order.
 *
 * **`UI-GOLD-001`'s whole claim lives here: the workspace refuses to submit against a stale
 * order.** Two accountants pricing the same order is the ordinary case rather than an edge one —
 * the first creates version 1 and moves the order, so the second, holding the version they read a
 * minute ago, is refused. Without the precondition they would silently supersede a price a
 * colleague had already quoted to a trader.
 *
 * That precondition had no source until this slice: `GET /gold-sale-orders/{id}` returned
 * `record_version` in the body and no `ETag`, so this screen could only have computed one — and a
 * computed precondition compares a state nobody observed.
 *
 * **The expected amount is never calculated here.** The server derives it from the weight and the
 * unit price; a second calculation on this screen would agree today and disagree the first time
 * rounding changed, and the number a trader is quoted would depend on which of the two they read.
 *
 * **No amount is editable directly.** A price is a unit price and a weight; entering a total
 * would make the unit price a derived figure nobody stated, which is the wrong way round for a
 * record that has to be explainable.
 */

type Phase =
  | {
      readonly kind: "ready";
      readonly order: GoldOrder;
      readonly ifMatch: string;
      readonly priced: PricingVersion | null;
    }
  | { readonly kind: "loading" }
  | { readonly kind: "failed" };

export default function AdminGoldOrderPage() {
  const parameters = useParams<{ orderId: string }>();
  const orderId = typeof parameters.orderId === "string" ? parameters.orderId : "";

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [unitPrice, setUnitPrice] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(
    async (signal?: AbortSignal): Promise<Phase> => {
      const { order, ifMatch } = await readOrder(orderId, signal);
      // The pricing version itself is not separately readable — the order names the current one
      // and M10 built no route that returns it. What the screen can show honestly is that a price
      // exists and what the order says it is; the version's own fields arrive with the command's
      // response, so the panel below fills in after a pricing.
      return { kind: "ready", order, ifMatch, priced: null };
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

  const price = async (ifMatch: string) => {
    setBusy(true);
    setNotice(null);
    try {
      const created = await createPricingVersion(orderId, ifMatch, {
        // `Number` here and not on the weight: a unit price in rials is a whole number the
        // contract types as an integer, where a weight is a decimal the string protects.
        unitPriceIrr: Number(unitPrice),
        pricingNote: note.trim() || null,
      });
      const refreshed = await load();
      setUnitPrice("");
      setNote("");
      setPhase(
        refreshed.kind === "ready" ? { ...refreshed, priced: created } : refreshed,
      );
    } catch (error) {
      // 412 means a colleague priced this order while this person was reading it — the event the
      // precondition exists for, and the one worth naming.
      const status = (error as { status?: number }).status;
      setNotice(status === 412 ? t("pricing.stale") : t("pricing.refused"));
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
    <AdminShell>
      <section aria-labelledby="pricing-heading" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-xl font-semibold" id="pricing-heading">
            {t("pricing.title")}
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
                <dt className="text-sm font-medium">{t("pricing.expectedAmount")}</dt>
                <dd>
                  {phase.order.expected_amount_irr === null ? (
                    <span>{t("pricing.none")}</span>
                  ) : (
                    <BidiText>{phase.order.expected_amount_irr}</BidiText>
                  )}
                </dd>
              </div>
            </dl>

            {notice !== null ? (
              <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
                {notice}
              </p>
            ) : null}

            {/* What the command just created, when it did. Shown from the command's own response
                rather than re-read: there is no route that returns a pricing version, so
                inventing a panel that pretended to read one would be a screen claiming a source
                it does not have. */}
            {phase.priced !== null ? (
              <section aria-labelledby="priced-heading" className="rounded border p-4">
                <h2 className="font-semibold" id="priced-heading">
                  {t("pricing.currentTitle")}
                </h2>
                <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                  <div>
                    <dt className="text-sm font-medium">{t("pricing.version")}</dt>
                    <dd>{phase.priced.version_number}</dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium">{t("pricing.method")}</dt>
                    <dd>
                      <BidiText>{phase.priced.pricing_method}</BidiText>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium">{t("pricing.unitPrice")}</dt>
                    <dd>
                      <BidiText>{phase.priced.unit_price_irr}</BidiText>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium">{t("pricing.expectedAmount")}</dt>
                    <dd>
                      <BidiText>{phase.priced.expected_amount_irr}</BidiText>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium">{t("pricing.contentHash")}</dt>
                    <dd className="break-all text-xs">
                      <BidiText>{phase.priced.content_hash}</BidiText>
                    </dd>
                  </div>
                </dl>
              </section>
            ) : null}

            <form
              aria-labelledby="new-pricing-heading"
              className="space-y-3 rounded border p-4"
              onSubmit={(event) => {
                event.preventDefault();
                void price(phase.ifMatch);
              }}
            >
              <h2 className="font-semibold" id="new-pricing-heading">
                {t("pricing.newTitle")}
              </h2>
              <p className="text-sm">{t("pricing.explains")}</p>

              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium">{t("pricing.unitPrice")}</span>
                <input
                  className="rounded border px-2 py-1"
                  disabled={busy}
                  inputMode="numeric"
                  onChange={(event) => setUnitPrice(event.target.value)}
                  required
                  value={unitPrice}
                />
              </label>

              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium">{t("pricing.note")}</span>
                <textarea
                  className="rounded border px-2 py-1"
                  disabled={busy}
                  onChange={(event) => setNote(event.target.value)}
                  rows={3}
                  value={note}
                />
              </label>

              <button className="rounded border px-3 py-1 font-bold" disabled={busy} type="submit">
                {t("pricing.submit")}
              </button>
            </form>
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}
