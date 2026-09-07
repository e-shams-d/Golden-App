"use client";

import { t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../components/admin-shell";
import {
  confirmPayment,
  listMatches,
  proposeMatch,
  readMatch,
  readReceipt,
  rejectMatch,
  type IncomingMatch,
  type IncomingReceipt,
} from "../../../src/incoming-payments";

/**
 * One claim that a trader paid, and the two judgements the centre makes about it.
 * §17.4 (`15_Agent_Implementation_Plan.md:1969`), §17.5 (`:1982`).
 *
 * M11 Screens, slice 6. M10 built propose, reject and confirm; nothing has ever called one from a
 * screen.
 *
 * **Two preconditions against two aggregates, and this screen is why the distinction was found.**
 * Confirming takes `If-Match` on the receipt; rejecting a candidate takes it on the *match*. Slice
 * 5's precondition gate had recorded both as the receipt's, and reading the routes to build this
 * page is what corrected it — so the reject handler reads the match for its own version rather
 * than reusing the one this page rendered.
 *
 * **Rejecting re-reads the match first, and that is not the mistake slice 3 recorded.** There the
 * screen must echo the version the *person* saw, because the guard exists to catch a change made
 * while they were reading. Here the list is a page of many rows and one `ETag` cannot describe
 * them, so the row's own read is the only server-issued precondition available — and it is one
 * request old rather than one page old, which is the distinction
 * `apps/admin-web/test/preconditions-come-from-the-server.test.ts` draws.
 *
 * **Proposing and confirming are different authorities.** `incoming_payment.match` suggests;
 * `incoming_payment.confirm` decides. The catalogue gives the manager a different conditional on
 * each, which is M0 saying the two acts are not one — so the server refuses independently and this
 * screen offers both without deciding who may use them. §20.1.
 */

type Phase =
  | { readonly kind: "loading" }
  | {
      readonly kind: "ready";
      readonly receipt: IncomingReceipt;
      readonly ifMatch: string;
      readonly matches: readonly IncomingMatch[];
    }
  | { readonly kind: "failed" };

export default function AdminIncomingPaymentPage() {
  const parameters = useParams<{ receiptId: string }>();
  const receiptId = typeof parameters.receiptId === "string" ? parameters.receiptId : "";

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const [rowId, setRowId] = useState("");
  const [proposeReason, setProposeReason] = useState("");
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectionReason, setRejectionReason] = useState("");
  const [confirmAmount, setConfirmAmount] = useState("");
  const [confirmNote, setConfirmNote] = useState("");
  const [confirmMatchId, setConfirmMatchId] = useState("");

  const load = useCallback(
    async (signal?: AbortSignal): Promise<Phase> => {
      const { receipt, ifMatch } = await readReceipt(receiptId, signal);
      const matches = await listMatches(receiptId, signal);
      return { kind: "ready", receipt, ifMatch, matches };
    },
    [receiptId],
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

  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    setNotice(null);
    try {
      await run();
      setPhase(await load());
    } catch (error) {
      const status = (error as { status?: number }).status;
      setNotice(status === 412 ? t("receipt.stale") : t("receipt.refused"));
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
      <section aria-labelledby="receipt-heading" className="space-y-4">
        <h1 className="text-xl font-semibold" id="receipt-heading">
          {t("receipt.reviewTitle")}
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
            description={t("receipt.loadFailed")}
            headingLevel={2}
            kind="error"
            title={t("receipt.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            <dl className="grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-sm font-medium">{t("receipt.status")}</dt>
                <dd>
                  <BidiText>{phase.receipt.status}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("receipt.claimedAmount")}</dt>
                <dd>
                  <BidiText>{phase.receipt.amount_irr}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("receipt.confirmedAmount")}</dt>
                <dd>
                  {/* `null` is "nobody has agreed yet", which is not zero — and on this screen the
                      difference decides whether the accountant still has work to do. */}
                  {phase.receipt.confirmed_amount_irr === null ? (
                    <span>{t("receipt.notConfirmedYet")}</span>
                  ) : (
                    <BidiText>{phase.receipt.confirmed_amount_irr}</BidiText>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("receipt.orderStatus")}</dt>
                <dd>
                  <BidiText>{phase.receipt.order_status}</BidiText>
                </dd>
              </div>
              {phase.receipt.tracking_number !== null ? (
                <div>
                  <dt className="text-sm font-medium">{t("receipt.tracking")}</dt>
                  <dd>
                    <BidiText>{phase.receipt.tracking_number}</BidiText>
                  </dd>
                </div>
              ) : null}
            </dl>

            {notice !== null ? (
              <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
                {notice}
              </p>
            ) : null}

            <section aria-labelledby="matches-heading" className="space-y-3">
              <h2 className="font-semibold" id="matches-heading">
                {t("receipt.matchesTitle")}
              </h2>

              {phase.matches.length === 0 ? (
                <p className="text-sm">{t("receipt.matchesEmpty")}</p>
              ) : (
                <ul className="space-y-3">
                  {/* Rejected candidates stay in the list. §10.7 keeps them because history nobody
                      can read is indistinguishable from a row that was removed — and the sequence
                      of judgements is what makes a confirmation reviewable. */}
                  {phase.matches.map((match) => (
                    <li className="rounded border p-3" data-status={match.status} key={match.id}>
                      <p className="text-sm">
                        <span className="font-medium">{t("receipt.matchStatus")}: </span>
                        <BidiText>{match.status}</BidiText>
                      </p>
                      <p className="text-sm">
                        <span className="font-medium">{t("receipt.matchRow")}: </span>
                        <BidiText>{match.bank_statement_row_id}</BidiText>
                      </p>
                      {match.match_reasons.length > 0 ? (
                        <p className="text-sm">
                          <span className="font-medium">{t("receipt.matchReasons")}: </span>
                          {match.match_reasons.join("، ")}
                        </p>
                      ) : null}
                      {match.rejected_at !== null ? (
                        <p className="text-sm">
                          <span className="font-medium">{t("receipt.matchRejectedAt")}: </span>
                          <BidiText>{match.rejected_at}</BidiText>
                          {match.rejection_reason !== null ? ` — ${match.rejection_reason}` : null}
                        </p>
                      ) : null}

                      {match.status === "proposed" ? (
                        <div className="mt-2 space-y-2">
                          <button
                            className="rounded border px-2 py-1 text-xs"
                            disabled={busy}
                            onClick={() =>
                              setRejectingId(rejectingId === match.id ? null : match.id)
                            }
                            type="button"
                          >
                            {t("receipt.reject")}
                          </button>
                          <button
                            className="rounded border px-2 py-1 text-xs"
                            disabled={busy}
                            onClick={() => setConfirmMatchId(match.id)}
                            type="button"
                          >
                            {t("receipt.confirm")}
                          </button>

                          {rejectingId === match.id ? (
                            <form
                              className="space-y-2"
                              onSubmit={(event) => {
                                event.preventDefault();
                                void act(async () => {
                                  // The *match's* own version, read now. The list is a page of
                                  // rows and one ETag cannot describe them all, so this is the
                                  // only server-issued precondition available for this row.
                                  const { ifMatch } = await readMatch(receiptId, match.id);
                                  await rejectMatch(
                                    receiptId,
                                    match.id,
                                    ifMatch,
                                    rejectionReason,
                                  );
                                  setRejectingId(null);
                                  setRejectionReason("");
                                });
                              }}
                            >
                              <p className="text-xs">{t("receipt.rejectExplains")}</p>
                              <label className="flex flex-col gap-1 text-xs">
                                <span className="font-medium">{t("receipt.rejectReason")}</span>
                                <textarea
                                  className="rounded border px-2 py-1"
                                  disabled={busy}
                                  onChange={(event) => setRejectionReason(event.target.value)}
                                  required
                                  rows={2}
                                  value={rejectionReason}
                                />
                              </label>
                              <button
                                className="rounded border px-2 py-1 text-xs"
                                disabled={busy}
                                type="submit"
                              >
                                {t("receipt.reject")}
                              </button>
                            </form>
                          ) : null}
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}

              <form
                className="space-y-2 rounded border p-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  void act(async () => {
                    await proposeMatch(
                      receiptId,
                      rowId,
                      proposeReason.trim() ? [proposeReason.trim()] : [],
                    );
                    setRowId("");
                    setProposeReason("");
                  });
                }}
              >
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("receipt.proposeRowId")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setRowId(event.target.value)}
                    required
                    value={rowId}
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("receipt.proposeReason")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setProposeReason(event.target.value)}
                    value={proposeReason}
                  />
                </label>
                <button className="rounded border px-3 py-1 text-sm" disabled={busy} type="submit">
                  {t("receipt.propose")}
                </button>
              </form>
            </section>

            {confirmMatchId !== "" ? (
              <form
                aria-labelledby="confirm-heading"
                className="space-y-3 rounded border p-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void act(async () => {
                    await confirmPayment(receiptId, phase.ifMatch, {
                      incomingPaymentMatchId: confirmMatchId,
                      confirmedAmountIrr: Number(confirmAmount),
                      confirmationNote: confirmNote.trim() || null,
                    });
                    setConfirmMatchId("");
                    setConfirmAmount("");
                    setConfirmNote("");
                  });
                }}
              >
                <h2 className="font-semibold" id="confirm-heading">
                  {t("receipt.confirmTitle")}
                </h2>
                {/* Said before the field. An overpayment is refused by the server and opens a
                    review task; telling somebody afterwards is telling them too late. */}
                <p className="text-sm">{t("receipt.confirmExplains")}</p>

                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("receipt.confirmAmount")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    inputMode="numeric"
                    onChange={(event) => setConfirmAmount(event.target.value)}
                    required
                    value={confirmAmount}
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("receipt.confirmNote")}</span>
                  <textarea
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setConfirmNote(event.target.value)}
                    rows={2}
                    value={confirmNote}
                  />
                </label>
                <button className="rounded border px-3 py-1 font-bold" disabled={busy} type="submit">
                  {t("receipt.confirm")}
                </button>
              </form>
            ) : null}
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}
