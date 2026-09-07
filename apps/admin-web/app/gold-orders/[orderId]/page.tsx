"use client";

import { t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../components/admin-shell";
import { closeOrder, recordDispatch } from "../../../src/dispatch";
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

  // M11 Screens slice 7. Dispatch and closure.
  const [dispatchType, setDispatchType] = useState("");
  const [dispatchWeight, setDispatchWeight] = useState("");
  const [recipient, setRecipient] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [closureNote, setClosureNote] = useState("");

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

  /**
   * Run one command and re-read, reporting a refusal as a refusal of *this attempt*.
   *
   * M11 Screens slice 7. The pricing handler below predates it and keeps its own body because it
   * also has to hold the created version for the panel; dispatch and closure have no such state,
   * so they share this.
   *
   * **412 is named separately** — on this screen it means a colleague moved the order while this
   * person was reading, which is the event the precondition exists for.
   */
  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    setNotice(null);
    try {
      await run();
      setPhase(await load());
    } catch (error) {
      const status = (error as { status?: number }).status;
      setNotice(status === 412 ? t("pricing.stale") : t("dispatch.refused"));
      try {
        setPhase(await load());
      } catch {
        setPhase({ kind: "failed" });
      }
    } finally {
      setBusy(false);
    }
  };

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

            {/*
              M11 Screens slice 7. Dispatch and closure, on the order's own page.

              **Three roles reach this screen and each may do a different thing here**: the
              accountant prices and closes, the warehouse dispatches, the manager and auditor read.
              `permission_catalog.yaml` gives `gold_sale.read` to all of them, so one page per
              order is the honest shape — a separate warehouse screen would be a second page about
              the same row, and the queues would have to choose between them.

              Every control is offered and the server refuses; §20.1. What the screen must not do
              is *pretend* to know which of them will be refused, because that would be a second
              copy of the catalogue.
            */}
            <section aria-labelledby="dispatch-heading" className="space-y-3 rounded border p-4">
              <h2 className="font-semibold" id="dispatch-heading">
                {t("dispatch.title")}
              </h2>

              {/*
                The pair the guard is about, shown together and before the form.

                Dispatching gold for an order that is not fully paid is what the override
                overrides, so the two numbers are the decision — and a screen showing the weight
                without them would ask somebody to authorise something they cannot see.
              */}
              <dl className="grid gap-3 sm:grid-cols-2">
                <div>
                  <dt className="text-sm font-medium">{t("dispatch.confirmedTotal")}</dt>
                  <dd>
                    <BidiText>{phase.order.final_amount_irr ?? 0}</BidiText>
                  </dd>
                </div>
                <div>
                  <dt className="text-sm font-medium">{t("dispatch.expectedAmount")}</dt>
                  <dd>
                    {phase.order.expected_amount_irr === null ? (
                      <span>{t("gold.notPricedYet")}</span>
                    ) : (
                      <BidiText>{phase.order.expected_amount_irr}</BidiText>
                    )}
                  </dd>
                </div>
              </dl>

              <form
                className="space-y-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  void act(async () => {
                    await recordDispatch(orderId, phase.ifMatch, {
                      dispatchType: dispatchType,
                      goldWeight: dispatchWeight.trim() || null,
                      weightUnit: phase.order.weight_unit,
                      recipientName: recipient.trim() || null,
                      // Absent means "do not override". An empty string would be a reason
                      // nobody wrote, recorded as though somebody had.
                      guardOverrideReason: overrideReason.trim() || null,
                    });
                    setDispatchWeight("");
                    setRecipient("");
                    setOverrideReason("");
                  });
                }}
              >
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("dispatch.type")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setDispatchType(event.target.value)}
                    required
                    value={dispatchType}
                  />
                </label>

                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("dispatch.weight")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    inputMode="decimal"
                    onChange={(event) => setDispatchWeight(event.target.value)}
                    value={dispatchWeight}
                  />
                </label>

                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("dispatch.recipient")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setRecipient(event.target.value)}
                    value={recipient}
                  />
                </label>

                {/*
                  The override, and it is the last field rather than one among many.

                  Filling it changes what the system allows: the server refuses a dispatch against
                  an unpaid order without it, and records `guard_override_at` with the reason when
                  it is present. So the explanation sits above the field rather than below the
                  button — somebody should read what they are authorising before they write it.
                */}
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("dispatch.override")}</span>
                  <span className="text-xs opacity-80" id="override-hint">
                    {t("dispatch.overrideExplains")}
                  </span>
                  <textarea
                    aria-describedby="override-hint"
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setOverrideReason(event.target.value)}
                    rows={2}
                    value={overrideReason}
                  />
                </label>

                <button className="rounded border px-3 py-1 font-bold" disabled={busy} type="submit">
                  {t("dispatch.record")}
                </button>
              </form>
            </section>

            <section aria-labelledby="close-heading" className="space-y-3 rounded border p-4">
              <h2 className="font-semibold" id="close-heading">
                {t("dispatch.closeTitle")}
              </h2>
              {/* A different grant from dispatching — `gold_sale.review` rather than
                  `gold_sale.dispatch` — so the person who handed the gold over is not necessarily
                  the person who declares the business finished. */}
              <p className="text-sm">{t("dispatch.closeExplains")}</p>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium">{t("dispatch.closureNote")}</span>
                <textarea
                  className="rounded border px-2 py-1"
                  disabled={busy}
                  onChange={(event) => setClosureNote(event.target.value)}
                  rows={2}
                  value={closureNote}
                />
              </label>
              <button
                className="rounded border px-3 py-1"
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    await closeOrder(orderId, phase.ifMatch, closureNote.trim() || null);
                    setClosureNote("");
                  })
                }
                type="button"
              >
                {t("dispatch.close")}
              </button>
            </section>
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}
