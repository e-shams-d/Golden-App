"use client";

import { t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
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
  | { readonly kind: "failed" };

export default function AdminGoldOrdersPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    listOrders(controller.signal)
      .then((orders) => setPhase({ kind: "ready", orders }))
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
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
