"use client";

import { t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../components/admin-shell";
import {
  confirmFailed,
  confirmPaid,
  createRetry,
  markRetryRequired,
  readAttempt,
  type PaymentAttempt,
} from "../../../src/payment-results";

/**
 * What the bank did with one attempt, and the four things the centre may record about it.
 * §16.4 (`15_Agent_Implementation_Plan.md:1859`), §16.5 (`:1870`), §16.6 (`:1880`).
 *
 * M11 Screens, slice 4. Every command here has existed since M9 and none has ever been issued from
 * a screen: results were confirmed by integration tests and by nothing else.
 *
 * **Reached from the queue, which is where this work actually arrives.** §19.2 gives the accountant
 * `sent-attempts-awaiting-result` and `failed-partial-retry-payments`, and slice 4 gave both a
 * `detail_path` so their rows link here. The destination is the *server's* answer — a mapping from
 * sixteen queue names to sixteen screens in the frontend would drift, and its failure mode is the
 * wrong screen for the right row.
 *
 * **`If-Match` is the ETag this page rendered, echoed.** `GET /payment-attempts/{id}` was added by
 * this slice precisely because nothing returned an attempt's version: all four commands require
 * the precondition and a screen could only have guessed one. A guessed precondition is present,
 * well-formed and meaningless.
 *
 * **After every command the page re-reads**, which is also how the next command gets a fresh
 * precondition. The optimistic alternative is shorter and wrong under failure: if the command is
 * refused, the screen has already reported that money was confirmed.
 *
 * **412 says what happened.** On this screen a stale precondition means another accountant
 * confirmed the same attempt while this one was reading — the exact event the header exists for —
 * and that is worth its own sentence rather than a generic refusal.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly attempt: PaymentAttempt; readonly ifMatch: string }
  | { readonly kind: "failed" };

/** Which form is open. Only one at a time: these are four different claims about one attempt. */
type Form = "none" | "paid" | "failed" | "retry-required" | "retry";

export default function AdminAttemptPage() {
  const parameters = useParams<{ attemptId: string }>();
  const attemptId = typeof parameters.attemptId === "string" ? parameters.attemptId : "";

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<Form>("none");
  const [notice, setNotice] = useState<string | null>(null);

  // Paid.
  const [tracking, setTracking] = useState("");
  const [resultAt, setResultAt] = useState("");
  const [unavailableReason, setUnavailableReason] = useState("");
  // Failed.
  const [failureCode, setFailureCode] = useState("");
  const [failureReason, setFailureReason] = useState("");
  // Retry, either kind.
  const [reason, setReason] = useState("");
  const [revisionId, setRevisionId] = useState("");
  const [amount, setAmount] = useState("");

  const load = useCallback(
    async (signal?: AbortSignal): Promise<Phase> => {
      const { attempt, ifMatch } = await readAttempt(attemptId, signal);
      return { kind: "ready", attempt, ifMatch };
    },
    [attemptId],
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
      setForm("none");
      setPhase(await load());
    } catch (error) {
      const status = (error as { status?: number }).status;
      setNotice(status === 412 ? t("attempt.stale") : t("attempt.refused"));
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
      <section aria-labelledby="attempt-heading" className="space-y-4">
        <h1 className="text-xl font-semibold" id="attempt-heading">
          {t("attempt.title")}
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
            description={t("attempt.failed")}
            headingLevel={2}
            kind="error"
            title={t("attempt.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            <dl className="grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-sm font-medium">{t("attempt.number")}</dt>
                <dd>{phase.attempt.attempt_number}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("attempt.status")}</dt>
                <dd>
                  <BidiText>{phase.attempt.status}</BidiText>
                </dd>
              </div>
              <div>
                {/* The amount the attempt already carries, shown and never sent back. §17
                    `:1131`'s "amount is exact" is honoured by the request bodies having no
                    amount field at all — a client figure could disagree with the row. */}
                <dt className="text-sm font-medium">{t("attempt.amount")}</dt>
                <dd>
                  <BidiText>{phase.attempt.amount_irr}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("attempt.requestStatus")}</dt>
                <dd>
                  <BidiText>{phase.attempt.request_status}</BidiText>
                </dd>
              </div>
              {phase.attempt.bank_tracking_number !== null ? (
                <div>
                  <dt className="text-sm font-medium">{t("attempt.tracking")}</dt>
                  <dd>
                    <BidiText>{phase.attempt.bank_tracking_number}</BidiText>
                  </dd>
                </div>
              ) : null}
              {phase.attempt.failure_code !== null ? (
                <div>
                  <dt className="text-sm font-medium">{t("attempt.failureCode")}</dt>
                  <dd>
                    <BidiText>{phase.attempt.failure_code}</BidiText>
                  </dd>
                </div>
              ) : null}
            </dl>

            {notice !== null ? (
              <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
                {notice}
              </p>
            ) : null}

            {/*
              **The controls are offered on the attempt's own status, and that is a deliberate
              exception to this application's usual rule.** Every other screen here reads
              `allowed_actions`; there is no such projection for attempts, and adding one would
              mean a second list beside four commands' guards for a surface with one caller.

              What makes it acceptable is that the server refuses regardless — §20.1, the frontend
              is not the control — and that the states are the commands' own:
              `06_Workflows_and_State_Machines.md:682-683` draws the arrows, and `sent` is the only
              status from which a result may be recorded. Recorded here rather than left as a
              difference somebody has to notice.
            */}
            {phase.attempt.confirmed_at === null ? (
              <div className="flex flex-wrap gap-2">
                <button
                  className="rounded border px-3 py-1"
                  disabled={busy}
                  onClick={() => setForm(form === "paid" ? "none" : "paid")}
                  type="button"
                >
                  {t("attempt.confirmPaid")}
                </button>
                <button
                  className="rounded border px-3 py-1"
                  disabled={busy}
                  onClick={() => setForm(form === "failed" ? "none" : "failed")}
                  type="button"
                >
                  {t("attempt.confirmFailed")}
                </button>
                <button
                  className="rounded border px-3 py-1"
                  disabled={busy}
                  onClick={() => setForm(form === "retry-required" ? "none" : "retry-required")}
                  type="button"
                >
                  {t("attempt.markRetryRequired")}
                </button>
              </div>
            ) : null}

            {phase.attempt.status === "retry_required" ? (
              <div>
                <button
                  className="rounded border px-3 py-1"
                  disabled={busy}
                  onClick={() => setForm(form === "retry" ? "none" : "retry")}
                  type="button"
                >
                  {t("attempt.createRetry")}
                </button>
              </div>
            ) : null}

            {form === "paid" ? (
              <form
                className="space-y-3 rounded border p-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void act(() =>
                    confirmPaid(attemptId, phase.ifMatch, {
                      bankTrackingNumber: tracking,
                      bankResultAt: resultAt,
                      // One or the other, never neither: the command's precondition is
                      // `evidence_policy_satisfied`, and a confirmation with no evidence and no
                      // explanation is the shape that policy exists to refuse. This slice offers
                      // the explanation; linking an evidence record is slice 6's surface.
                      evidenceUnavailableReason: unavailableReason,
                    }),
                  );
                }}
              >
                <p className="text-sm">{t("attempt.paidNeedsBankFacts")}</p>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("attempt.tracking")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setTracking(event.target.value)}
                    required
                    value={tracking}
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("attempt.resultAt")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setResultAt(event.target.value)}
                    required
                    type="datetime-local"
                    value={resultAt}
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("attempt.evidenceUnavailable")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setUnavailableReason(event.target.value)}
                    required
                    value={unavailableReason}
                  />
                </label>
                <button className="rounded border px-3 py-1" disabled={busy} type="submit">
                  {t("attempt.submit")}
                </button>
              </form>
            ) : null}

            {form === "failed" ? (
              <form
                className="space-y-3 rounded border p-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void act(() =>
                    confirmFailed(attemptId, phase.ifMatch, {
                      failureCode: failureCode,
                      failureReason: failureReason,
                    }),
                  );
                }}
              >
                {/* `failure_code` is a free field, not a dropdown. The contract types it as a
                    plain string and no catalogue names a set — the same reason
                    `app/commands/trader_result.py` refused to enumerate a dispute reason. A list
                    invented on this screen becomes the closed list nobody approved. */}
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("attempt.failureCode")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setFailureCode(event.target.value)}
                    required
                    value={failureCode}
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("attempt.failureReason")}</span>
                  <textarea
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setFailureReason(event.target.value)}
                    required
                    rows={3}
                    value={failureReason}
                  />
                </label>
                <button className="rounded border px-3 py-1" disabled={busy} type="submit">
                  {t("attempt.submit")}
                </button>
              </form>
            ) : null}

            {form === "retry-required" ? (
              <form
                className="space-y-3 rounded border p-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void act(() => markRetryRequired(attemptId, phase.ifMatch, reason));
                }}
              >
                <p className="text-sm">{t("attempt.retryRequiredCreatesNothing")}</p>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("attempt.reason")}</span>
                  <textarea
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setReason(event.target.value)}
                    required
                    rows={3}
                    value={reason}
                  />
                </label>
                <button className="rounded border px-3 py-1" disabled={busy} type="submit">
                  {t("attempt.submit")}
                </button>
              </form>
            ) : null}

            {form === "retry" ? (
              <form
                className="space-y-3 rounded border p-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void act(() =>
                    createRetry(attemptId, phase.ifMatch, {
                      paymentRequestRevisionId: revisionId,
                      amountIrr: Number(amount),
                      reason,
                    }),
                  );
                }}
              >
                {/* The one command here that takes an amount, and it is not a contradiction: a
                    retry is a *new* attempt whose amount is a decision — the unresolved
                    remainder — rather than a restatement of what the bank already holds. */}
                <p className="text-sm">{t("attempt.retryAmountIsADecision")}</p>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("attempt.revisionId")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setRevisionId(event.target.value)}
                    required
                    value={revisionId}
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("attempt.retryAmount")}</span>
                  <input
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    inputMode="numeric"
                    onChange={(event) => setAmount(event.target.value)}
                    required
                    value={amount}
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("attempt.reason")}</span>
                  <textarea
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setReason(event.target.value)}
                    required
                    rows={3}
                    value={reason}
                  />
                </label>
                <button className="rounded border px-3 py-1" disabled={busy} type="submit">
                  {t("attempt.submit")}
                </button>
              </form>
            ) : null}
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}
