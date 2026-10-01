"use client";

import { t, type MessageKey } from "@gold/localization";
import { stateForError, type ApplicationState } from "@gold/api-client";
import { BidiText, StateView, kindForApplicationState } from "@gold/ui";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminShell } from "../../components/admin-shell";
import { listOrders, type GoldOrder } from "../../src/gold-orders";

/**
 * Every gold order the centre may see, as the way into pricing one.
 * §17.2 (`15_Agent_Implementation_Plan.md:1944`).
 *
 * M11 Screens, slice 5.
 *
 * **Reached from the navigation rather than from a queue**, and that is not an oversight: §19.2
 * names twenty-four queues and none of them is "orders awaiting a price". The warehouse's three
 * gold queues are about *dispatch*, which is slice 7. So pricing arrives through a list, and the
 * navigation item carries `gold_sale.read` — the grant the list route itself checks.
 *
 * A person who may read orders but not price them sees this screen and no pricing form on the
 * detail page: the form is the centre's, guarded by `gold_sale.price`, and the server refuses
 * regardless. §20.1 — the frontend is not the control.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly orders: readonly GoldOrder[] }
  // **`state`, not `failed`.** A reader who may not price orders also may not read them,
  // and this screen used to answer that with "the list could not be fetched, please try
  // again" — a refusal dressed as a hiccup, inviting a retry that can never succeed.
  // `/admin-users` was the first screen to route failures through `stateForError`, and its
  // own note says the mapping had been built and used by nothing. This is the second.
  | { readonly kind: "state"; readonly state: ApplicationState };

/**
 * What to say about a failure, which is not the same question as how to draw it.
 *
 * Changing the icon and leaving the sentence is the original fault with a new colour: a
 * reader who may not read these orders was told the list "could not be fetched, please
 * try again", and no number of retries would change the answer. The state's own strings
 * are the ones written for this; the screen's wording survives only for `error`, where it
 * says more than the generic string does.
 */
function textForState(state: ApplicationState): {
  readonly title: string;
  readonly description: string;
} {
  const kind = kindForApplicationState(state);
  if (kind === "error") {
    return { description: t("gold.failed"), title: t("gold.failedTitle") };
  }
  return {
    description: t(`state.${kind}.description` as MessageKey),
    title: t(`state.${kind}.title` as MessageKey),
  };
}

export default function AdminGoldOrdersPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    listOrders(controller.signal)
      .then((orders) => setPhase({ kind: "ready", orders }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const state = stateForError(error);
        // `undefined` is an abort the signal did not report; there is nothing to render.
        if (state !== undefined) setPhase({ kind: "state", state });
      });
    return () => controller.abort();
  }, []);

  return (
    <AdminShell>
      <section aria-labelledby="gold-list-heading" className="space-y-4">
        <h1 className="text-xl font-semibold" id="gold-list-heading">
          {t("gold.listTitle")}
        </h1>

        {phase.kind === "loading" ? (
          <StateView
            description={t("state.loading.description")}
            headingLevel={2}
            kind="loading"
            title={t("state.loading.title")}
          />
        ) : null}

        {phase.kind === "state" ? (
          <StateView
            description={textForState(phase.state).description}
            headingLevel={2}
            kind={kindForApplicationState(phase.state)}
            title={textForState(phase.state).title}
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
                        <BidiText>
                          {order.gold_weight} {order.weight_unit}
                        </BidiText>
                      </td>
                      <td>
                        {/* "Not yet priced" is the state this screen exists to act on, so it is
                            said in words rather than left as an empty cell. */}
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
    </AdminShell>
  );
}
