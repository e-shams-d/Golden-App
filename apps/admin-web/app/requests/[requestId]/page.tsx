"use client";

import { paymentRequestStatusLabel, t, toPersianDigits } from "@gold/localization";
import { StateView } from "@gold/ui";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../components/admin-shell";
import {
  listRevisions,
  markEligible,
  readRequest,
  requestCorrection,
  startReview,
  type DetailWithPrecondition,
  type Revision,
} from "../../../src/payment-requests";

/**
 * One request, its history, and the centre's three decisions.
 *
 * **Marking eligible is not manager approval.** `12_Security_RBAC_Audit.md:904` says so in one
 * sentence and the screen says it too, in Persian, next to the button — because the phrase
 * "تأیید برای پرداخت" invites exactly that misreading, and an accountant who believes they are
 * approving a payment is an accountant operating under the wrong idea of their own authority.
 * Slice 9 gates the property; this sentence is for the person.
 *
 * **Which buttons appear comes from `allowed_actions`.** The server derives it from the same
 * tables the commands guard with, so the screen never decides for itself that a transition is
 * legal. Advisory rather than a control — the command still refuses, and
 * `12_Security_RBAC_Audit.md:625-626` keeps the backend authoritative — but it means no button
 * here answers 400.
 *
 * **Every decision re-reads first.** The `If-Match` is one request old, never one page old:
 * between rendering and clicking, the trader may have filed a correction. `mark_eligible`
 * carries the revision id from the read that populated this screen, so a correction that
 * landed while the accountant was reading fails the command instead of quietly approving a
 * revision nobody looked at.
 */

type Phase =
  | { readonly kind: "loading" }
  | {
      readonly kind: "ready";
      readonly detail: DetailWithPrecondition;
      readonly history: readonly Revision[];
      readonly currentRevisionId: string | null;
    }
  | { readonly kind: "forbidden" }
  | { readonly kind: "failed" };

const START_REVIEW = "payment_request.start_review";
const REQUEST_CORRECTION = "payment_request.request_correction";
const MARK_ELIGIBLE = "payment_request.mark_eligible";

export default function AdminRequestPage() {
  const parameters = useParams<{ requestId: string }>();
  const requestId = parameters.requestId;

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | undefined>(undefined);

  const [reasonCode, setReasonCode] = useState("");
  const [messageToTrader, setMessageToTrader] = useState("");
  const [internalNote, setInternalNote] = useState("");
  const [reviewNote, setReviewNote] = useState("");

  const phaseForError = (error: unknown): Phase =>
    (error as { status?: number }).status === 403 ? { kind: "forbidden" } : { kind: "failed" };

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const detail = await readRequest(requestId, signal);
      const history = await listRevisions(requestId, signal);
      return {
        kind: "ready" as const,
        detail,
        history: history.items,
        currentRevisionId: history.current_revision_id,
      };
    },
    [requestId],
  );

  const refresh = useCallback(async () => {
    try {
      setPhase(await load());
    } catch (error) {
      setPhase(phaseForError(error));
    }
  }, [load]);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then(setPhase)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setPhase(phaseForError(error));
      });
    return () => controller.abort();
  }, [load]);

  const decide = useCallback(
    async (what: "review" | "correction" | "eligible") => {
      setNotice(undefined);

      if (what === "correction" && (!reasonCode.trim() || !messageToTrader.trim())) {
        setNotice(t("admin.request.correctionNeedsBoth"));
        return;
      }

      setBusy(true);
      try {
        // Re-read for the precondition. One request old, not one page old.
        const fresh = await readRequest(requestId);
        if (what === "review") {
          await startReview(requestId, fresh.ifMatch);
        } else if (what === "correction") {
          await requestCorrection(requestId, fresh.ifMatch, {
            reasonCode: reasonCode.trim(),
            messageToTrader: messageToTrader.trim(),
            internalNote: internalNote.trim() || null,
          });
          setReasonCode("");
          setMessageToTrader("");
          setInternalNote("");
        } else {
          const revisionId = fresh.detail.request.current_revision_id;
          if (!revisionId) {
            setNotice(t("admin.request.actionFailed"));
            return;
          }
          await markEligible(requestId, fresh.ifMatch, {
            expectedRevisionId: revisionId,
            reviewNote: reviewNote.trim() || null,
          });
          setReviewNote("");
        }
        await refresh();
      } catch (error) {
        const status = (error as { status?: number }).status;
        setNotice(status === 412 ? t("admin.request.stale") : t("admin.request.actionFailed"));
        if (status === 412) await refresh();
      } finally {
        setBusy(false);
      }
    },
    [internalNote, messageToTrader, reasonCode, refresh, requestId, reviewNote],
  );

  if (phase.kind === "loading") {
    return (
      <AdminShell>
        <StateView
          headingLevel={1}
          description={t("admin.request.loading")}
          kind="loading"
          title={t("admin.request.loading")}
        />
      </AdminShell>
    );
  }

  if (phase.kind === "forbidden") {
    return (
      <AdminShell>
        <StateView
          headingLevel={1}
          description={t("admin.requests.forbidden")}
          kind="forbidden"
          title={t("admin.requests.forbiddenTitle")}
        />
      </AdminShell>
    );
  }

  if (phase.kind === "failed") {
    return (
      <AdminShell>
        <StateView
          headingLevel={1}
          description={t("admin.request.failed")}
          kind="error"
          title={t("admin.request.failedTitle")}
        />
      </AdminShell>
    );
  }

  const { request, allowed_actions: allowed } = phase.detail.detail;

  return (
    <AdminShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h1 className="text-3xl font-black">{t("admin.request.title")}</h1>
          <span className="font-mono font-bold" dir="ltr">
            {request.request_number}
          </span>
        </div>

        <p className="mt-3">
          <span className="text-[var(--ink-600)]">{t("trader.request.status")}: </span>
          <span className="font-bold">{paymentRequestStatusLabel(request.status)}</span>
        </p>

        {request.review_note ? (
          <p className="mt-4 rounded-xl border border-[var(--border)] p-4 leading-7">
            <span className="font-bold">{t("admin.request.reviewNote")}: </span>
            {request.review_note}
          </p>
        ) : null}

        {notice ? (
          <p
            className="mt-4 rounded-xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-4 leading-7"
            role="alert"
          >
            {notice}
          </p>
        ) : null}

        <section className="mt-6">
          <h2 className="text-xl font-black">{t("admin.request.history")}</h2>
          <ul className="mt-3 flex flex-col gap-3">
            {phase.history.map((revision) => (
              <li
                className={`rounded-xl border p-4 ${
                  revision.id === phase.currentRevisionId
                    ? "border-[var(--gold-500)]"
                    : "border-[var(--border)]"
                }`}
                key={revision.id}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-bold">
                    {t("trader.request.revision")} {toPersianDigits(revision.revision_number)}
                  </span>
                  {revision.id === phase.currentRevisionId ? (
                    <span className="rounded-full bg-[var(--gold-700)] px-3 py-1 text-sm text-white">
                      {t("trader.request.current")}
                    </span>
                  ) : null}
                </div>
                <p className="mt-2">
                  {revision.beneficiary_name_snapshot}
                  <span className="mx-2 font-mono" dir="ltr">
                    {revision.beneficiary_iban_snapshot}
                  </span>
                </p>
                <p className="mt-1" dir="ltr">
                  {revision.entered_amount
                    ? `${toPersianDigits(revision.entered_amount.value)} ${
                        revision.entered_amount.unit === "TOMAN"
                          ? t("money.unit.TOMAN")
                          : t("money.unit.IRR")
                      } → ${toPersianDigits(revision.amount_irr)} ${t("money.unit.IRR")}`
                    : `${toPersianDigits(revision.amount_irr)} ${t("money.unit.IRR")}`}
                </p>
                {revision.description ? (
                  <p className="mt-1 text-[var(--ink-600)]">{revision.description}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>

        {allowed.includes(START_REVIEW) ? (
          <div className="mt-6">
            <button
              className="rounded-lg bg-[var(--gold-700)] px-6 py-3 font-bold text-white disabled:opacity-60"
              disabled={busy}
              onClick={() => void decide("review")}
              type="button"
            >
              {busy ? t("admin.request.working") : t("admin.request.startReview")}
            </button>
          </div>
        ) : null}

        {allowed.includes(REQUEST_CORRECTION) ? (
          <section className="mt-8 rounded-2xl border border-[var(--border)] p-5">
            <h2 className="text-xl font-black">{t("admin.request.requestCorrection")}</h2>
            <form
              className="mt-4 flex max-w-2xl flex-col gap-4"
              onSubmit={(event) => {
                event.preventDefault();
                void decide("correction");
              }}
            >
              <label className="flex flex-col gap-2">
                <span className="font-bold">{t("admin.request.reasonCode")}</span>
                <input
                  className="rounded-lg border border-[var(--border)] px-3 py-2"
                  onChange={(event) => setReasonCode(event.target.value)}
                  required
                  type="text"
                  value={reasonCode}
                />
              </label>
              <label className="flex flex-col gap-2">
                <span className="font-bold">{t("admin.request.messageToTrader")}</span>
                {/* What the trader's screen renders. Required, because a return with no
                    message is a request whose owner cannot tell what to change. */}
                <textarea
                  className="rounded-lg border border-[var(--border)] px-3 py-2"
                  onChange={(event) => setMessageToTrader(event.target.value)}
                  required
                  rows={3}
                  value={messageToTrader}
                />
              </label>
              <label className="flex flex-col gap-2">
                <span className="font-bold">{t("admin.request.internalNote")}</span>
                {/* Audit-only. It is never rendered to the trader and never returned by any
                    read, which is what "trader responses omit internal-only data" means. */}
                <textarea
                  className="rounded-lg border border-[var(--border)] px-3 py-2"
                  onChange={(event) => setInternalNote(event.target.value)}
                  rows={2}
                  value={internalNote}
                />
              </label>
              <div>
                <button
                  className="rounded-lg border border-[var(--border)] px-6 py-3 font-bold disabled:opacity-60"
                  disabled={busy}
                  type="submit"
                >
                  {busy ? t("admin.request.working") : t("admin.request.requestCorrection")}
                </button>
              </div>
            </form>
          </section>
        ) : null}

        {allowed.includes(MARK_ELIGIBLE) ? (
          <section className="mt-8 rounded-2xl border border-[var(--border)] p-5">
            <h2 className="text-xl font-black">{t("admin.request.markEligible")}</h2>
            <p className="mt-2 font-bold leading-8">{t("admin.request.notManagerApproval")}</p>
            <form
              className="mt-4 flex max-w-2xl flex-col gap-4"
              onSubmit={(event) => {
                event.preventDefault();
                void decide("eligible");
              }}
            >
              <label className="flex flex-col gap-2">
                <span className="font-bold">{t("admin.request.reviewNote")}</span>
                <textarea
                  className="rounded-lg border border-[var(--border)] px-3 py-2"
                  onChange={(event) => setReviewNote(event.target.value)}
                  rows={2}
                  value={reviewNote}
                />
              </label>
              <div>
                <button
                  className="rounded-lg bg-[var(--gold-700)] px-6 py-3 font-bold text-white disabled:opacity-60"
                  disabled={busy}
                  type="submit"
                >
                  {busy ? t("admin.request.working") : t("admin.request.markEligible")}
                </button>
              </div>
            </form>
          </section>
        ) : null}
      </section>
    </AdminShell>
  );
}
