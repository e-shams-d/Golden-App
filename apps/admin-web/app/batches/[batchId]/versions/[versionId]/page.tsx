"use client";

import { t, toPersianDigits } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../../../components/admin-shell";
import { type DecisionKind, DecisionDialog } from "../../../../../components/decision-dialog";
import { adminAuthAdapter } from "../../../../../src/auth";
import {
  APPROVE_PURPOSE,
  type ApprovalView,
  approveVersion,
  fingerprint,
  isStale,
  readApprovalView,
  REJECT_PURPOSE,
  rejectVersion,
  STEP_UP_RESOURCE_TYPE,
  tomanFromIrr,
} from "../../../../../src/batches";

/**
 * What a manager decides on. §13.3 of the screen specification, field by field.
 *
 * **Nineteen mandatory fields, and the two that are easiest to leave out are the two that
 * matter.** "Finalizer identity" and "separation-of-duty status" are what tell a manager whether
 * this decision is theirs to take — and the second is the one a screen would naturally omit,
 * because the server refuses anyway. It refuses *after* somebody has read the whole file and
 * pressed a button, which is the wrong moment to learn it.
 *
 * **The separation status is not computed here.** It arrives decided, per actor, with the reason
 * naming which rule refuses. A client-side comparison would be a second opinion about a rule the
 * database enforces, and the two would eventually disagree.
 *
 * **The content hash is rendered as a fingerprint and carried whole.** §13.3 asks for a
 * "fingerprint", and twelve hex characters is what a person can compare by eye; the full digest
 * is what slice 2's approve command will quote back. S-2 records the choice.
 *
 * **Toman is derived here and nowhere else.** §13.3 asks for "total IRR and Toman equivalent";
 * `MONEY_TIME_CONTRACT.md:17` makes IRR integer strings the wire format, so the equivalent is a
 * rendering. S-1.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly view: ApprovalView }
  | { readonly kind: "forbidden" }
  | { readonly kind: "missing" }
  | { readonly kind: "failed" };

export default function ApprovalDetailPage({
  params,
}: {
  params: Promise<{ batchId: string; versionId: string }>;
}) {
  const { batchId, versionId } = use(params);
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });

  const phaseForError = (error: unknown): Phase => {
    const status = (error as { status?: number }).status;
    if (status === 403) return { kind: "forbidden" };
    if (status === 404) return { kind: "missing" };
    return { kind: "failed" };
  };

  const load = useCallback(
    (signal?: AbortSignal) =>
      readApprovalView(batchId, versionId, signal)
        .then((view) => setPhase({ kind: "ready", view }))
        .catch((error: unknown) => {
          if (!signal?.aborted) setPhase(phaseForError(error));
        }),
    [batchId, versionId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return (
    <AdminShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("admin.approval.title")}</h1>

        {phase.kind === "loading" ? (
          <StateView
            description={t("admin.approval.loading")}
            headingLevel={2}
            kind="loading"
            title={t("admin.approval.loading")}
          />
        ) : null}

        {phase.kind === "forbidden" ? (
          <StateView
            description={t("admin.approval.forbidden")}
            headingLevel={2}
            kind="forbidden"
            title={t("admin.approval.forbiddenTitle")}
          />
        ) : null}

        {phase.kind === "missing" ? (
          <StateView
            description={t("admin.approval.missing")}
            headingLevel={2}
            kind="empty"
            title={t("admin.approval.missingTitle")}
          />
        ) : null}

        {phase.kind === "failed" ? (
          <StateView
            actions={
              <button
                className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-2 font-bold"
                onClick={() => void load()}
                type="button"
              >
                {t("common.refresh")}
              </button>
            }
            description={t("admin.approval.failed")}
            headingLevel={2}
            kind="error"
            title={t("admin.approval.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            {/*
              §13.4. The version this page was rendered from is no longer the batch's current one,
              which means somebody replaced it while the manager was reading. Five behaviours, and
              the page does all five: the command is blocked (the decision section is not
              rendered at all), the banner is prominent, the current version is linked, the page
              below stays readable as history, and — the one that needs saying — an open dialog is
              not transferred. It cannot be: `Decide` is not rendered in this branch, so a dialog
              inside it unmounts rather than re-targeting.
            */}
            {isStale(versionId, phase.view) ? (
              <div
                className="mt-4 rounded-2xl border-2 border-[var(--danger-600)] bg-[var(--danger-50)] p-4"
                data-testid="stale-banner"
                role="alert"
              >
                <p className="text-lg font-black">{t("admin.decide.staleTitle")}</p>
                <p className="mt-2 leading-8">{t("admin.decide.staleBody")}</p>
                <Link
                  className="mt-3 inline-block rounded-lg border border-[var(--danger-600)] px-3 py-1 font-bold"
                  data-testid="stale-current-link"
                  href={`/batches/${phase.view.batch.id}/versions/${phase.view.version.id}`}
                >
                  {t("admin.decide.staleLink")}
                </Link>
              </div>
            ) : (
              <Decide
                batchId={phase.view.batch.id}
                onDecided={() => void load()}
                view={phase.view}
              />
            )}
            <Detail view={phase.view} />
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}

/**
 * The decision, and the step-up it needs. §13.5 and §13.6.
 *
 * **The hash is captured when the dialog opens.** `openFor` stores it alongside the version id,
 * and `DecisionDialog` never receives either — the request is built here from what was captured,
 * so there is no path by which a re-read value could be sent. `UI-APPROVE-001`.
 *
 * **Nothing is shown as decided until the server says so.** `onDecided` is called after the
 * response and reloads the view; there is no local "approved" state to be wrong. `UI-APPROVE-002`.
 *
 * **Not rendered at all when the caller may not decide.** The separation status arrives from the
 * server, and a screen that offered the button anyway would be inviting a refusal rather than
 * explaining one.
 */
function Decide({
  batchId,
  onDecided,
  view,
}: {
  readonly batchId: string;
  readonly onDecided: () => void;
  readonly view: ApprovalView;
}) {
  const [open, setOpen] = useState<DecisionKind | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Captured at open time, from the view this component was rendered with. Read once so a later
  // re-render cannot change what a dialog already open would submit.
  const [captured, setCaptured] = useState<{ hash: string; versionId: string } | null>(null);

  if (view.prior_decision) {
    return (
      <p className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-subtle)] p-4">
        {t("admin.decide.recorded")}
      </p>
    );
  }

  if (!view.separation_of_duty.may_decide) return null;

  const openFor = (kind: DecisionKind) => {
    setCaptured({ hash: view.version.content_hash, versionId: view.version.id });
    setError(null);
    setOpen(kind);
  };

  const submit = ({ password, reason }: { password: string; reason: string }) => {
    if (!captured || open === null) return;
    setBusy(true);
    setError(null);

    const purpose = open === "approve" ? APPROVE_PURPOSE : REJECT_PURPOSE;
    const idempotencyKey = crypto.randomUUID();

    // The step-up is obtained for *this* action and *this* version, then **spent immediately**.
    //
    // The adapter is called directly rather than through `createAuthClient`, which is what this
    // app already does everywhere else — and here it is also the right shape: a recent-auth
    // context is single-use, so holding one in a cache to reuse would be holding something the
    // server will refuse the second time. `getRecentAuth`'s resource binding still matters for
    // any caller that does cache, which is why slice 2 fixed it.
    void adminAuthAdapter
      .reauthenticate({
        actionClass: purpose,
        challengeResponse: password,
        resourceType: STEP_UP_RESOURCE_TYPE,
        resourceId: captured.versionId,
      })
      .then((context) =>
        open === "approve"
          ? approveVersion({
              batchId,
              versionId: captured.versionId,
              expectedContentHash: captured.hash,
              recentAuthReference: context.reference,
              idempotencyKey,
            })
          : rejectVersion({
              batchId,
              versionId: captured.versionId,
              expectedContentHash: captured.hash,
              recentAuthReference: context.reference,
              idempotencyKey,
              reasonCode: "manager_rejected",
              reason,
            }),
      )
      .then(() => {
        // Only now. The server has recorded it; the reload is what makes the screen say so.
        setOpen(null);
        setCaptured(null);
        onDecided();
      })
      .catch((caught: unknown) => {
        const message = (caught as { body?: { error?: { message?: string } } }).body?.error
          ?.message;
        setError(message ?? t("admin.decide.failed"));
      })
      .finally(() => setBusy(false));
  };

  if (open !== null) {
    return (
      <DecisionDialog
        busy={busy}
        error={error}
        kind={open}
        onCancel={() => {
          setOpen(null);
          setCaptured(null);
        }}
        onSubmit={submit}
      />
    );
  }

  return (
    <div className="mt-4 flex flex-wrap gap-3">
      <button
        className="rounded-lg bg-[var(--gold-700)] px-4 py-2 font-bold text-white"
        data-testid="open-approve"
        onClick={() => openFor("approve")}
        type="button"
      >
        {t("admin.decide.approve")}
      </button>
      <button
        className="rounded-lg border border-[var(--danger-600)] px-4 py-2 font-bold text-[var(--danger-600)]"
        data-testid="open-reject"
        onClick={() => openFor("reject")}
        type="button"
      >
        {t("admin.decide.reject")}
      </button>
    </div>
  );
}

function Detail({ view }: { view: ApprovalView }) {
  const warnings = view.version.validation_summary.warnings ?? [];

  return (
    <>
      {/* The separation status first, because it decides whether the rest is actionable. */}
      <div
        className={`mt-4 rounded-2xl border p-4 ${
          view.separation_of_duty.may_decide
            ? "border-[var(--border)] bg-[var(--surface-subtle)]"
            : "border-[var(--danger-600)] bg-[var(--danger-50)]"
        }`}
        data-testid="separation-of-duty"
        role="status"
      >
        <p className="font-bold">
          {view.separation_of_duty.may_decide
            ? t("admin.approval.mayDecide")
            : t("admin.approval.mayNotDecide")}
        </p>
        {view.separation_of_duty.reason ? (
          <p className="mt-1 text-[var(--ink-600)]">{view.separation_of_duty.reason}</p>
        ) : null}
      </div>

      {view.prior_decision ? (
        <div
          className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-subtle)] p-4"
          data-testid="prior-decision"
        >
          <p className="font-bold">
            {t("admin.approval.priorDecision")}: {view.prior_decision.decision}
          </p>
          {view.prior_decision.reason ? (
            <p className="mt-1 text-[var(--ink-600)]">{view.prior_decision.reason}</p>
          ) : null}
        </div>
      ) : null}

      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
        <Cell label={t("admin.approval.batchReference")}>{view.batch.batch_number}</Cell>
        <Cell label={t("admin.approval.exactVersion")}>
          {toPersianDigits(String(view.version.version_number))}
        </Cell>
        <Cell label={t("admin.approval.immutableStatus")}>{view.version.status}</Cell>
        <Cell label={t("admin.approval.totalIrr")}>
          {toPersianDigits(view.version.total_amount_irr)}
        </Cell>
        <Cell label={t("admin.approval.totalToman")}>
          {toPersianDigits(tomanFromIrr(view.version.total_amount_irr))}
        </Cell>
        <Cell label={t("admin.approval.requestCount")}>
          {toPersianDigits(String(view.request_count))}
        </Cell>
        <Cell label={t("admin.approval.rowCount")}>
          {toPersianDigits(String(view.version.row_count))}
        </Cell>
        <Cell label={t("admin.approval.traderCount")}>
          {toPersianDigits(String(view.trader_count))}
        </Cell>
        <Cell label={t("admin.approval.beneficiaryCount")}>
          {toPersianDigits(String(view.beneficiary_count))}
        </Cell>
        <Cell label={t("admin.approval.bank")}>{view.bank ?? t("common.unknown")}</Cell>
        <Cell label={t("admin.approval.bankProfileVersion")}>
          {view.bank_profile_version_number === null
            ? t("common.unknown")
            : toPersianDigits(String(view.bank_profile_version_number))}
        </Cell>
        <Cell label={t("admin.approval.mappingVersion")}>
          {view.mapping_version === null
            ? t("common.unknown")
            : toPersianDigits(String(view.mapping_version))}
        </Cell>
        <Cell label={t("admin.approval.sourceAccount")}>
          {view.source_account ?? t("common.unknown")}
        </Cell>
        <Cell label={t("admin.approval.preparedBy")}>
          {view.prepared_by ?? t("common.unknown")}
        </Cell>
        <Cell label={t("admin.approval.finalizedBy")}>
          {view.finalized_by ?? t("admin.batches.notFinalized")}
        </Cell>
        <Cell label={t("admin.approval.fingerprint")}>
          <code data-testid="content-hash-fingerprint" title={view.version.content_hash}>
            {fingerprint(view.version.content_hash)}
          </code>
        </Cell>
      </dl>

      <h2 className="mt-8 text-2xl font-black">{t("admin.approval.warnings")}</h2>
      {warnings.length === 0 ? (
        <p className="mt-2 text-[var(--ink-600)]">{t("admin.approval.noWarnings")}</p>
      ) : (
        <ul className="mt-2 list-disc ps-6" data-testid="warnings">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      <h2 className="mt-8 text-2xl font-black">{t("admin.approval.rows")}</h2>
      <ul className="mt-2 grid gap-2" data-testid="ordered-rows">
        {view.items.map((item) => (
          <li
            className="rounded-xl border border-[var(--border)] bg-[var(--surface-subtle)] p-3"
            key={item.id}
          >
            <span className="font-bold">{toPersianDigits(String(item.row_order))}.</span>{" "}
            {item.beneficiary_name} — {item.beneficiary_iban} —{" "}
            {toPersianDigits(item.amount_irr)}
          </li>
        ))}
      </ul>

      <h2 className="mt-8 text-2xl font-black">{t("admin.approval.preview")}</h2>
      {view.preview_export_id ? (
        <Link
          className="mt-2 inline-block rounded-lg border border-[var(--border)] px-3 py-1 font-bold"
          data-testid="preview-export-link"
          href={`/bank-exports/${view.preview_export_id}`}
        >
          {t("admin.approval.previewAvailable")}
        </Link>
      ) : (
        <p className="mt-2 text-[var(--ink-600)]">{t("admin.approval.noPreview")}</p>
      )}
    </>
  );
}

function Cell({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div>
      <dt className="text-sm text-[var(--ink-600)]">{label}</dt>
      <dd className="font-bold">{children}</dd>
    </div>
  );
}
