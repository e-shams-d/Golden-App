"use client";

import { t } from "@gold/localization";
import { StateView } from "@gold/ui";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../components/admin-shell";
import { approveTrader, listTraders, readTrader, rejectTrader, type Trader } from "../../src/traders";

/**
 * The screen that turns approval from a database task into an operator's.
 *
 * **Every decision re-reads the business first.** The list is a snapshot, and between
 * rendering it and clicking a button another operator may have acted. So the handler
 * calls `readTrader` and sends back the `ETag` that read returned — the `If-Match` is
 * always one request old, never one page old. When it is stale the backend answers 412
 * and this shows the version-conflict state rather than retrying with a newer value,
 * because a decision the operator did not see the current state of is not their decision.
 *
 * **The buttons are not the control.** `12_Security_RBAC_Audit.md:625-626` makes the
 * backend authoritative; hiding a button for a caller without `trader.approve` would be
 * a convenience, and the 403 is what actually refuses them. This screen therefore shows
 * the refusal rather than pretending the action was never available.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly traders: readonly Trader[] }
  | { readonly kind: "forbidden" }
  | { readonly kind: "failed" };

const PENDING = "pending_approval";

/** Persian for a stored status, or the raw value if something new appears. */
function statusLabel(value: string): string {
  const known: Record<string, string> = {
    pending_approval: t("status.pending_approval"),
    approved: t("status.approved"),
    rejected: t("status.rejected"),
    active: t("status.active"),
    inactive: t("status.inactive"),
    suspended: t("status.suspended"),
  };
  return known[value] ?? value;
}

export default function AdminTradersPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busyId, setBusyId] = useState<string | undefined>(undefined);
  const [notice, setNotice] = useState<string | undefined>(undefined);
  const [reasons, setReasons] = useState<Record<string, string>>({});

  // A 403 is a different screen from a 500: one says "not for you", the other says "try
  // again". Rendering the same panel for both would send an operator to fix a network
  // they cannot fix.
  const phaseForError = (error: unknown): Phase =>
    (error as { status?: number }).status === 403 ? { kind: "forbidden" } : { kind: "failed" };

  const refresh = useCallback(async () => {
    try {
      setPhase({ kind: "ready", traders: await listTraders() });
    } catch (error) {
      setPhase(phaseForError(error));
    }
  }, []);

  // The initial load subscribes to the fetch and updates state from its callback, rather
  // than awaiting inside the effect body: `react-hooks/set-state-in-effect` refuses the
  // second shape, and it is right to — an effect that sets state synchronously can
  // cascade renders. The abort on unmount is the other half: without it, navigating away
  // mid-request sets state on a component that is gone.
  useEffect(() => {
    const controller = new AbortController();
    listTraders(controller.signal)
      .then((traders) => setPhase({ kind: "ready", traders }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setPhase(phaseForError(error));
      });
    return () => controller.abort();
  }, []);

  const decide = useCallback(
    async (trader: Trader, action: "approve" | "reject") => {
      setNotice(undefined);
      const reason = (reasons[trader.id] ?? "").trim();
      if (action === "reject" && !reason) {
        setNotice(t("admin.traders.reasonRequired"));
        return;
      }

      setBusyId(trader.id);
      try {
        // Re-read for the precondition. See the note above: one request old, not one
        // page old.
        const current = await readTrader(trader.id);
        if (action === "approve") {
          await approveTrader(trader.id, current.ifMatch);
        } else {
          await rejectTrader(trader.id, current.ifMatch, reason);
        }
        await refresh();
      } catch (error) {
        const status = (error as { status?: number }).status;
        setNotice(status === 412 ? t("admin.traders.stale") : t("admin.traders.decisionFailed"));
        // A stale precondition means somebody else moved; showing them the new truth is
        // more useful than leaving the old rows on screen.
        if (status === 412) await refresh();
      } finally {
        setBusyId(undefined);
      }
    },
    [reasons, refresh],
  );

  return (
    <AdminShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("admin.traders.title")}</h1>
        <p className="mt-3 max-w-3xl leading-8 text-[var(--ink-600)]">
          {t("admin.traders.description")}
        </p>

        {notice ? (
          <p
            className="mt-4 rounded-xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-4 leading-7"
            role="alert"
          >
            {notice}
          </p>
        ) : null}

        <div className="mt-6">
          {phase.kind === "loading" ? (
            <StateView
              headingLevel={2}
              description={t("admin.traders.loading")}
              kind="loading"
              title={t("admin.traders.loading")}
            />
          ) : null}

          {phase.kind === "forbidden" ? (
            <StateView
              headingLevel={2}
              description={t("admin.traders.forbidden")}
              kind="forbidden"
              title={t("admin.traders.forbiddenTitle")}
            />
          ) : null}

          {phase.kind === "failed" ? (
            <StateView
              headingLevel={2}
              actions={
                <button
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-2 font-bold"
                  onClick={() => void refresh()}
                  type="button"
                >
                  {t("admin.traders.refresh")}
                </button>
              }
              description={t("admin.traders.failed")}
              kind="error"
              title={t("admin.traders.failedTitle")}
            />
          ) : null}

          {phase.kind === "ready" && phase.traders.length === 0 ? (
            <StateView
              headingLevel={2}
              description={t("admin.traders.empty")}
              kind="empty"
              title={t("admin.traders.emptyTitle")}
            />
          ) : null}

          {phase.kind === "ready" && phase.traders.length > 0 ? (
            <table className="w-full border-collapse text-start">
              <caption className="sr-only">{t("admin.traders.title")}</caption>
              <thead>
                <tr className="border-b border-[var(--border)] text-sm text-[var(--ink-600)]">
                  <th className="p-3 text-start" scope="col">
                    {t("admin.traders.name")}
                  </th>
                  <th className="p-3 text-start" scope="col">
                    {t("admin.traders.phone")}
                  </th>
                  <th className="p-3 text-start" scope="col">
                    {t("admin.traders.status")}
                  </th>
                  <th className="p-3 text-start" scope="col">
                    {t("admin.traders.actions")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {phase.traders.map((trader) => (
                  <tr className="border-b border-[var(--border)] align-top" key={trader.id}>
                    <td className="p-3 font-bold">{trader.display_name}</td>
                    {/* The phone is a Latin-digit identifier inside a right-to-left
                        page, so it is isolated: without `dir="ltr"` the leading `+`
                        renders at the wrong end and the number reads as a different
                        one. */}
                    <td className="p-3" dir="ltr">
                      {trader.primary_phone}
                    </td>
                    <td className="p-3">{statusLabel(trader.approval_status)}</td>
                    <td className="p-3">
                      {trader.approval_status === PENDING ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            className="rounded-lg bg-[var(--gold-700)] px-4 py-2 font-bold text-white disabled:opacity-60"
                            disabled={busyId === trader.id}
                            onClick={() => void decide(trader, "approve")}
                            type="button"
                          >
                            {busyId === trader.id
                              ? t("admin.traders.working")
                              : t("admin.traders.approve")}
                          </button>
                          <label className="flex items-center gap-2">
                            <span className="sr-only">{t("admin.traders.reasonLabel")}</span>
                            <input
                              className="rounded-lg border border-[var(--border)] px-3 py-2"
                              onChange={(event) =>
                                setReasons((current) => ({
                                  ...current,
                                  [trader.id]: event.target.value,
                                }))
                              }
                              placeholder={t("admin.traders.reasonLabel")}
                              type="text"
                              value={reasons[trader.id] ?? ""}
                            />
                          </label>
                          <button
                            className="rounded-lg border border-[var(--border)] px-4 py-2 font-bold disabled:opacity-60"
                            disabled={busyId === trader.id}
                            onClick={() => void decide(trader, "reject")}
                            type="button"
                          >
                            {t("admin.traders.reject")}
                          </button>
                        </div>
                      ) : (
                        <span className="text-[var(--ink-600)]">—</span>
                      )}
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
