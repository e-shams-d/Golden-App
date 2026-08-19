"use client";

import { normalizeDigits, paymentRequestStatusLabel, t, toPersianDigits } from "@gold/localization";
import { StateView } from "@gold/ui";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { TraderShell } from "../../../components/trader-shell";
import {
  createRevision,
  listRevisions,
  readRequest,
  submitRequest,
  type AmountUnit,
  type DetailWithPrecondition,
  type Revision,
} from "../../../src/payment-requests";
import { amountForDisplay, correctionNotice, markCurrent } from "../../../src/request-view";

/**
 * One request as its owner sees it: what the centre said, what every revision held, and what
 * they may do next.
 *
 * **The reviewer's note is the first thing on the screen when it exists.** `UI-REQ-001` is
 * blunt about why: a request returned without the reason visible is a request the trader
 * resubmits unchanged. The note reaches this screen because slice 8 found it had nowhere to
 * live — `return_for_correction` recorded it in the audit trail only, which no trader reads,
 * so document 04's `review_note` column stayed empty and the correction screen had nothing
 * to show.
 *
 * **The buttons come from `allowed_actions`.** The server computes them from the same tables
 * the commands guard with, so this screen offers what the server said rather than deciding
 * for itself which transition is legal. It is advisory and not a control: the command still
 * refuses, and `12_Security_RBAC_Audit.md:625-626` keeps it that way. What it buys is a
 * screen that does not offer a button which answers 400.
 *
 * **Every command re-reads first.** The `If-Match` is one request old, never one page old —
 * `admin-web/app/traders/page.tsx` states the reasoning at length and it holds here.
 */

type Phase =
  | { readonly kind: "loading" }
  | {
      readonly kind: "ready";
      readonly detail: DetailWithPrecondition;
      readonly history: readonly Revision[];
      readonly currentRevisionId: string | null;
    }
  | { readonly kind: "failed" };

const CREATE_REVISION = "payment_request.create_revision";
const SUBMIT = "payment_request.submit";

export default function TraderRequestPage() {
  const parameters = useParams<{ requestId: string }>();
  const requestId = parameters.requestId;

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | undefined>(undefined);

  const [value, setValue] = useState("");
  const [unit, setUnit] = useState<AmountUnit>("TOMAN");
  const [description, setDescription] = useState("");
  const [reason, setReason] = useState("");

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
      const next = await load();
      setPhase(next);
      // The form starts from what is currently on the request, so a correction is an edit of
      // the real content rather than a blank slate the trader has to retype.
      const revision = next.detail.detail.current_revision;
      if (revision) {
        setValue(revision.entered_amount?.value ?? revision.amount_irr);
        setUnit((revision.entered_amount?.unit as AmountUnit | undefined) ?? "IRR");
        setDescription(revision.description ?? "");
      }
    } catch {
      setPhase({ kind: "failed" });
    }
  }, [load]);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((next) => {
        setPhase(next);
        const revision = next.detail.detail.current_revision;
        if (revision) {
          setValue(revision.entered_amount?.value ?? revision.amount_irr);
          setUnit((revision.entered_amount?.unit as AmountUnit | undefined) ?? "IRR");
          setDescription(revision.description ?? "");
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, [load]);

  const act = useCallback(
    async (what: "submit" | "correct") => {
      setNotice(undefined);
      setBusy(true);
      try {
        // Re-read for the precondition: one request old, not one page old.
        const fresh = await readRequest(requestId);
        if (what === "submit") {
          await submitRequest(requestId, fresh.ifMatch);
        } else {
          const digits = normalizeDigits(value).trim();
          if (!digits) {
            setNotice(t("trader.newRequest.amountRequired"));
            return;
          }
          await createRevision(requestId, fresh.ifMatch, {
            beneficiaryId: fresh.detail.request.beneficiary_id,
            value: digits,
            unit,
            description: description.trim() || null,
            revisionReason: reason.trim() || null,
          });
        }
        await refresh();
      } catch (error) {
        const status = (error as { status?: number }).status;
        setNotice(status === 412 ? t("trader.request.stale") : t("trader.request.actionFailed"));
        if (status === 412) await refresh();
      } finally {
        setBusy(false);
      }
    },
    [description, reason, refresh, requestId, unit, value],
  );

  if (phase.kind === "loading") {
    return (
      <TraderShell>
        <StateView
          headingLevel={1}
          description={t("trader.request.loading")}
          kind="loading"
          title={t("trader.request.loading")}
        />
      </TraderShell>
    );
  }

  if (phase.kind === "failed") {
    return (
      <TraderShell>
        <StateView
          headingLevel={1}
          description={t("trader.request.failed")}
          kind="error"
          title={t("trader.request.failedTitle")}
        />
      </TraderShell>
    );
  }

  const { request, allowed_actions: allowed } = phase.detail.detail;
  const mayCorrect = allowed.includes(CREATE_REVISION);
  const maySubmit = allowed.includes(SUBMIT);
  const notice_from_centre = correctionNotice(request);
  const rows = markCurrent(phase.history, phase.currentRevisionId);

  return (
    <TraderShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h1 className="text-3xl font-black">{t("trader.request.title")}</h1>
          <span className="font-mono font-bold" dir="ltr">
            {request.request_number}
          </span>
        </div>

        <p className="mt-3">
          <span className="text-[var(--ink-600)]">{t("trader.request.status")}: </span>
          <span className="font-bold">{paymentRequestStatusLabel(request.status)}</span>
        </p>

        {notice_from_centre ? (
          <section className="mt-5 rounded-2xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-5">
            <h2 className="text-xl font-black">{t("trader.requests.reviewNote")}</h2>
            <p className="mt-2 leading-8">{notice_from_centre}</p>
          </section>
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
          <h2 className="text-xl font-black">{t("trader.request.history")}</h2>
          <ul className="mt-3 flex flex-col gap-3">
            {rows.map(({ revision, isCurrent }) => {
              const amount = amountForDisplay(revision);
              return (
                <li
                  className={`rounded-xl border p-4 ${
                    isCurrent ? "border-[var(--gold-500)]" : "border-[var(--border)]"
                  }`}
                  key={revision.id}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-bold">
                      {t("trader.request.revision")} {toPersianDigits(revision.revision_number)}
                    </span>
                    {isCurrent ? (
                      <span className="rounded-full bg-[var(--gold-700)] px-3 py-1 text-sm text-white">
                        {t("trader.request.current")}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-2">
                    {revision.beneficiary_name_snapshot} —{" "}
                    <span dir="ltr">
                      {toPersianDigits(amount.value)}{" "}
                      {amount.unit === "TOMAN" ? t("money.unit.TOMAN") : t("money.unit.IRR")}
                    </span>
                  </p>
                  {revision.description ? (
                    <p className="mt-1 text-[var(--ink-600)]">{revision.description}</p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>

        {mayCorrect ? (
          <section className="mt-8 rounded-2xl border border-[var(--border)] p-5">
            <h2 className="text-xl font-black">{t("trader.request.correctTitle")}</h2>
            <p className="mt-2 leading-8 text-[var(--ink-600)]">
              {t("trader.request.correctBody")}
            </p>
            <form
              className="mt-4 flex max-w-2xl flex-col gap-4"
              onSubmit={(event) => {
                event.preventDefault();
                void act("correct");
              }}
            >
              <div className="flex flex-wrap items-end gap-4">
                <label className="flex flex-1 flex-col gap-2">
                  <span className="font-bold">{t("trader.newRequest.amount")}</span>
                  <input
                    className="rounded-lg border border-[var(--border)] px-3 py-2"
                    dir="ltr"
                    inputMode="numeric"
                    onChange={(event) => setValue(event.target.value)}
                    type="text"
                    value={value}
                  />
                </label>
                <label className="flex flex-col gap-2">
                  <span className="font-bold">{t("trader.newRequest.unit")}</span>
                  <select
                    className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
                    onChange={(event) => setUnit(event.target.value as AmountUnit)}
                    value={unit}
                  >
                    <option value="TOMAN">{t("money.unit.TOMAN")}</option>
                    <option value="IRR">{t("money.unit.IRR")}</option>
                  </select>
                </label>
              </div>
              <label className="flex flex-col gap-2">
                <span className="font-bold">{t("trader.newRequest.note")}</span>
                <textarea
                  className="rounded-lg border border-[var(--border)] px-3 py-2"
                  onChange={(event) => setDescription(event.target.value)}
                  rows={2}
                  value={description}
                />
              </label>
              <label className="flex flex-col gap-2">
                <span className="font-bold">{t("trader.request.reason")}</span>
                <input
                  className="rounded-lg border border-[var(--border)] px-3 py-2"
                  onChange={(event) => setReason(event.target.value)}
                  type="text"
                  value={reason}
                />
              </label>
              <div>
                <button
                  className="rounded-lg border border-[var(--border)] px-6 py-3 font-bold disabled:opacity-60"
                  disabled={busy}
                  type="submit"
                >
                  {busy ? t("admin.request.working") : t("trader.request.saveRevision")}
                </button>
              </div>
            </form>
          </section>
        ) : null}

        {maySubmit ? (
          <div className="mt-6">
            <button
              className="rounded-lg bg-[var(--gold-700)] px-6 py-3 font-bold text-white disabled:opacity-60"
              disabled={busy}
              onClick={() => void act("submit")}
              type="button"
            >
              {busy ? t("admin.request.working") : t("trader.request.submit")}
            </button>
          </div>
        ) : null}

        {!mayCorrect && !maySubmit ? (
          <p className="mt-6 leading-8 text-[var(--ink-600)]">
            {t("trader.request.nothingAllowed")}
          </p>
        ) : null}
      </section>
    </TraderShell>
  );
}
