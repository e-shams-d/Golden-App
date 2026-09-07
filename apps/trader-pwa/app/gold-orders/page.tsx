"use client";

import { t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { TraderShell } from "../../components/trader-shell";
import { createOrder, listOrders, type GoldOrder } from "../../src/gold-orders";

/**
 * The trader's gold orders, and the form that files a new one.
 * §9.12 (`15_Agent_Implementation_Plan.md:1287`), §17.1 (`:1931`).
 *
 * M11 Screens, slice 5. M10 built this aggregate and no trader has ever created an order.
 *
 * **The list and the form on one screen**, rather than a separate `/new` route as payment requests
 * have. The difference is the form: a payment request needs a beneficiary chosen from a list and a
 * revision history to sit beside, where a gold order is four fields and no prior state. A second
 * route would be a page whose only content is a form somebody already has room for.
 *
 * **No amount anywhere on this screen.** The trader states what gold they want; the centre decides
 * what it costs. `expected_amount_irr` is rendered on the detail screen once a price exists, and
 * the absence here is the honest shape of §17.2: pricing is not the trader's to enter.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly orders: readonly GoldOrder[] }
  | { readonly kind: "failed" };

const UNITS = ["GRAM", "KILOGRAM"] as const;

export default function TraderGoldOrdersPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const [goldType, setGoldType] = useState("");
  const [weight, setWeight] = useState("");
  const [unit, setUnit] = useState<string>(UNITS[0]);
  const [purity, setPurity] = useState("");

  const load = useCallback(async (signal?: AbortSignal): Promise<Phase> => {
    return { kind: "ready", orders: await listOrders(signal) };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((next) => setPhase(next))
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, [load]);

  const file = async () => {
    setBusy(true);
    setNotice(null);
    try {
      await createOrder({
        goldType,
        // The string as typed. Parsing it to a number here would round a weight the person
        // entered to three decimal places, which is the thing the string type exists to prevent.
        goldWeight: weight,
        weightUnit: unit,
        goldPurity: purity,
      });
      setGoldType("");
      setWeight("");
      setPurity("");
      setPhase(await load());
    } catch {
      setNotice(t("gold.createFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <TraderShell>
      <section aria-labelledby="gold-heading" className="space-y-6">
        <h1 className="text-xl font-semibold" id="gold-heading">
          {t("gold.listTitle")}
        </h1>

        <form
          aria-labelledby="new-order-heading"
          className="space-y-3 rounded border p-4"
          onSubmit={(event) => {
            event.preventDefault();
            void file();
          }}
        >
          <h2 className="font-semibold" id="new-order-heading">
            {t("gold.createTitle")}
          </h2>
          <p className="text-sm">{t("gold.createExplains")}</p>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">{t("gold.type")}</span>
            <span className="text-xs opacity-80" id="gold-type-hint">
              {t("gold.typeHint")}
            </span>
            <input
              aria-describedby="gold-type-hint"
              className="rounded border px-2 py-1"
              disabled={busy}
              onChange={(event) => setGoldType(event.target.value)}
              required
              value={goldType}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">{t("gold.weight")}</span>
            <span className="text-xs opacity-80" id="gold-weight-hint">
              {t("gold.weightHint")}
            </span>
            <input
              aria-describedby="gold-weight-hint"
              className="rounded border px-2 py-1"
              disabled={busy}
              inputMode="decimal"
              onChange={(event) => setWeight(event.target.value)}
              required
              value={weight}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">{t("gold.unit")}</span>
            <select
              className="rounded border px-2 py-1"
              disabled={busy}
              onChange={(event) => setUnit(event.target.value)}
              value={unit}
            >
              {UNITS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">{t("gold.purity")}</span>
            <input
              className="rounded border px-2 py-1"
              disabled={busy}
              onChange={(event) => setPurity(event.target.value)}
              required
              value={purity}
            />
          </label>

          {notice !== null ? (
            <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
              {notice}
            </p>
          ) : null}

          <button className="rounded border px-3 py-1 font-bold" disabled={busy} type="submit">
            {t("gold.create")}
          </button>
        </form>

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
            description={t("gold.failed")}
            headingLevel={2}
            kind="error"
            title={t("gold.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          phase.orders.length === 0 ? (
            <StateView
              description={t("gold.listEmptyDescription")}
              headingLevel={2}
              kind="empty"
              title={t("gold.listEmptyTitle")}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-start text-sm">
                <thead>
                  <tr>
                    <th scope="col">{t("gold.orderNumber")}</th>
                    <th scope="col">{t("gold.status")}</th>
                    <th scope="col">{t("gold.weight")}</th>
                    <th scope="col">{t("gold.expectedAmount")}</th>
                  </tr>
                </thead>
                <tbody>
                  {phase.orders.map((order) => (
                    <tr data-status={order.status} key={order.id}>
                      <td>
                        <Link href={`/gold-orders/${order.id}`}>
                          <BidiText>{order.order_number}</BidiText>
                        </Link>
                      </td>
                      <td>
                        <BidiText>{order.status}</BidiText>
                      </td>
                      <td>
                        {/* The weight as the server holds it — a string, never re-formatted. */}
                        <BidiText>
                          {order.gold_weight} {order.weight_unit}
                        </BidiText>
                      </td>
                      <td>
                        {/* `null` is "not yet priced", which is not zero. Rendering 0 would tell a
                            trader the centre had quoted them nothing. */}
                        {order.expected_amount_irr === null ? (
                          <span>{t("gold.notPricedYet")}</span>
                        ) : (
                          <BidiText>{order.expected_amount_irr}</BidiText>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : null}
      </section>
    </TraderShell>
  );
}
