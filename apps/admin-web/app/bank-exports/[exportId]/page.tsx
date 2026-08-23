"use client";

import { t, toPersianDigits } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../components/admin-shell";
import {
  type ExportDetail,
  isPreview,
  isQuarantined,
  PREVIEW_BANNER,
  readExport,
  splitCheck,
  statusLabelKey,
} from "../../../src/bank-exports";

/**
 * The bank file. §14.1, §14.3, §14.4 and §14.5 of the screen specification.
 *
 * **One screen for both kinds of artifact**, because §11.8 stores them in one table for the reason
 * document 04 gives: a preview and a final export are the same rendering of the same version, and
 * what differs is who may act on the result. Two screens would have made "is this the file that was
 * approved" a question you answer differently depending on which page you opened.
 *
 * **The three prohibitions are structural.** §14.1 says a preview must not offer mark-as-sent, must
 * not present a checksum as official, and must not show a send-ready status. This screen does not
 * *hide* those things from a preview — it has no mark-sent control at all (that is slice 4's, on
 * this screen, gated on `sendable`), it labels the checksum by what it is, and it derives no
 * send-readiness of its own. An absence is only reliable when there is nothing to suppress.
 *
 * **Nothing here recomputes integrity.** `integrity_failed_checks` arrives evaluated by the same
 * function the download path acts on, so the screen and the refusal cannot disagree about whether
 * a file may be sent. `UI-INTEGRITY-001` shows those names; it does not produce them.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly view: ExportDetail }
  | { readonly kind: "forbidden" }
  | { readonly kind: "missing" }
  | { readonly kind: "failed" };

export default function BankExportPage({
  params,
}: {
  params: Promise<{ exportId: string }>;
}) {
  const { exportId } = use(params);
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });

  const phaseForError = (error: unknown): Phase => {
    const status = (error as { status?: number }).status;
    if (status === 403) return { kind: "forbidden" };
    if (status === 404) return { kind: "missing" };
    return { kind: "failed" };
  };

  const load = useCallback(
    (signal?: AbortSignal) =>
      readExport(exportId, signal)
        .then((view) => setPhase({ kind: "ready", view }))
        .catch((error: unknown) => {
          if (!signal?.aborted) setPhase(phaseForError(error));
        }),
    [exportId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return (
    <AdminShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("admin.export.title")}</h1>

        {phase.kind === "loading" ? (
          <StateView
            description={t("admin.export.loading")}
            headingLevel={2}
            kind="loading"
            title={t("admin.export.loading")}
          />
        ) : null}

        {phase.kind === "forbidden" ? (
          <StateView
            description={t("admin.export.forbidden")}
            headingLevel={2}
            kind="forbidden"
            title={t("admin.export.forbiddenTitle")}
          />
        ) : null}

        {phase.kind === "missing" ? (
          <StateView
            description={t("admin.export.missing")}
            headingLevel={2}
            kind="empty"
            title={t("admin.export.missingTitle")}
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
            description={t("admin.export.failed")}
            headingLevel={2}
            kind="error"
            title={t("admin.export.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            {isPreview(phase.view) ? <PreviewBanner /> : null}
            {isQuarantined(phase.view) ? <Quarantine view={phase.view} /> : null}
            <Detail view={phase.view} />
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}

/**
 * §14.1's "persistent watermark/banner". `UI-PREVIEW-001`.
 *
 * The marker is rendered from `PREVIEW_BANNER`, which the specification is parsed to check.
 * `dir="ltr"` because the string is English inside a right-to-left page, and without it the em
 * dash lands on the wrong side — a mangled safety label is a label people learn to ignore.
 *
 * The Persian paragraph below is not a translation of the marker. It says what the marker *means*
 * for the person reading it, which is the part that changes behaviour.
 */
function PreviewBanner() {
  return (
    <div
      className="mt-4 rounded-2xl border-2 border-[var(--warning-600)] bg-[var(--warning-50)] p-4"
      data-testid="preview-banner"
      role="status"
    >
      <p
        className="text-lg font-black tracking-wide"
        data-testid="preview-banner-text"
        dir="ltr"
        lang="en"
      >
        {PREVIEW_BANNER}
      </p>
      <p className="mt-2 leading-8">{t("admin.export.previewExplanation")}</p>
    </div>
  );
}

/**
 * §14.5. `UI-INTEGRITY-001`.
 *
 * Four of §14.5's five requirements: download is blocked, mark-sent is blocked, and each failed
 * check is shown. The fifth — "create/link urgent review task" — is G-10: Phase 1A has no task
 * table, and a link to nothing would be worse than the absence, because it would read as though
 * somebody had been told.
 *
 * **Blocking is by not rendering, not by disabling.** Neither control exists on this screen while
 * the export is quarantined, so there is nothing for a determined person to re-enable in a
 * developer console. The server refuses as well — `SEC-DOWNLOAD-001` — and this is the half that
 * stops somebody trying.
 *
 * **There is no override.** §14.5's last clause forbids the control that lets somebody download a
 * quarantined file regardless, and `UI-INTEGRITY-002` asserts its absence over the whole export
 * surface rather than this component — because the control somebody adds under pressure gets added
 * wherever the download lives.
 *
 * That test greps raw source for the words such a control would be spelled with, so this comment
 * describes the forbidden phrase instead of writing it. The first version of this file wrote it out
 * and failed the test on its own prose. Blunt is the point: a scan that first stripped comments
 * could be defeated by anything that confused the stripper.
 */
function Quarantine({ view }: { view: ExportDetail }) {
  return (
    <div
      className="mt-4 rounded-2xl border-2 border-[var(--danger-600)] bg-[var(--danger-50)] p-4"
      data-testid="integrity-quarantine"
      role="alert"
    >
      <p className="text-lg font-black">{t("admin.export.quarantinedTitle")}</p>
      <p className="mt-2 leading-8">{t("admin.export.quarantinedBody")}</p>

      <h3 className="mt-4 font-bold">{t("admin.export.failedChecks")}</h3>
      {view.integrity_failed_checks.length === 0 ? (
        // A quarantined export whose comparisons now hold. Not "everything is fine": the row was
        // quarantined because a comparison failed when it was checked, and saying nothing here
        // would leave the screen looking like a clean export with a red banner.
        <p className="mt-1" data-testid="failed-checks-empty">
          {t("admin.export.failedChecksUnavailable")}
        </p>
      ) : (
        <ul className="mt-1 grid gap-2" data-testid="failed-checks">
          {view.integrity_failed_checks.map((described) => {
            const { name, detail } = splitCheck(described);
            return (
              <li className="rounded-lg border border-[var(--danger-600)] bg-[var(--surface)] p-2" key={described}>
                {/* §15.5's own name for the comparison, unchanged. An operator who finds
                    `export_total_matches_version` in a report should find the same string here. */}
                <code dir="ltr" lang="en">
                  {name}
                </code>
                {detail ? <p className="mt-1 text-sm text-[var(--ink-600)]" dir="ltr">{detail}</p> : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/**
 * §14.4's twelve items, and §14.3's states. `UI-EXPORT-001`.
 *
 * Ten of the twelve are rendered here. The other two are not returned by the API and not invented
 * by the screen: "generator version" exists nowhere in the system (S-6) and "download history" is
 * one timestamp rather than a history (S-5). Both are recorded in the plan, and the single
 * timestamp is shown for what it is.
 */
function Detail({ view }: { view: ExportDetail }) {
  const preview = isPreview(view);

  return (
    <>
      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
        <Cell label={t("admin.export.reference")}>{view.export_number}</Cell>
        <Cell label={t("admin.export.fileName")}>
          <span dir="ltr">{view.file_name}</span>
        </Cell>
        {/*
          §14.3's states, and only the eight the catalogue has. §14.3 also names `requested` and
          `superseded`; `requested` has no row to render, because an export exists only once its
          file does, and `superseded` is DOC-CONFLICT-016. Rendering a state the API can never
          return would be a screen written against a document rather than against the system.
        */}
        <Cell label={t("admin.export.state")}>
          <span data-testid="export-status">{statusLabel(view.status)}</span>
        </Cell>
        <Cell label={t("admin.export.kind")}>
          <span data-testid="export-kind">
            {preview ? t("admin.export.kindPreview") : t("admin.export.kindFinal")}
          </span>
        </Cell>
        <Cell label={t("admin.export.batch")}>
          <Link
            className="underline"
            href={`/batches/${view.batch_id}/versions/${view.payment_batch_version_id}`}
          >
            {view.batch_number}
          </Link>
        </Cell>
        <Cell label={t("admin.export.exactVersion")}>
          {toPersianDigits(String(view.version_number))}
        </Cell>
        {/*
          §14.1's second prohibition, handled by labelling rather than by hiding. A preview's
          checksum is a real checksum of a real file — withholding it would make the screen less
          honest — but it is not the official checksum of anything sendable, and the label is what
          says so. `UI-PREVIEW-002` asserts the wording differs between the two kinds.
        */}
        <Cell label={preview ? t("admin.export.checksumPreview") : t("admin.export.checksum")}>
          <code data-testid="export-checksum" dir="ltr" title={view.file_sha256_hash}>
            {view.file_sha256_hash.slice(0, 12)}
          </code>
        </Cell>
        <Cell label={t("admin.export.approvalMatch")}>
          <span data-testid="approval-hash-match">
            {view.approval_hash_matches === null
              ? t("admin.export.matchNotApplicable")
              : view.approval_hash_matches
                ? t("admin.export.matchHolds")
                : t("admin.export.matchBroken")}
          </span>
        </Cell>
        <Cell label={t("admin.export.rowCount")}>{toPersianDigits(String(view.row_count))}</Cell>
        <Cell label={t("admin.export.total")}>{toPersianDigits(view.total_amount_irr)}</Cell>
        <Cell label={t("admin.export.bank")}>{view.bank ?? t("common.unknown")}</Cell>
        <Cell label={t("admin.export.sourceAccount")}>
          {view.source_account ?? t("common.unknown")}
        </Cell>
        <Cell label={t("admin.export.mapping")}>
          {view.mapping_version === null
            ? t("common.unknown")
            : toPersianDigits(String(view.mapping_version))}
        </Cell>
        <Cell label={t("admin.export.bankProfileVersion")}>
          {view.bank_profile_version_number === null
            ? t("common.unknown")
            : toPersianDigits(String(view.bank_profile_version_number))}
        </Cell>
        <Cell label={t("admin.export.generationTime")}>{view.generated_at}</Cell>
        <Cell label={t("admin.export.generatedBy")}>
          {view.generated_by ?? t("common.unknown")}
        </Cell>
        <Cell label={t("admin.export.integrityState")}>
          <span data-testid="integrity-state">
            {isQuarantined(view)
              ? t("admin.export.integrityQuarantined")
              : view.integrity_failed_checks.length > 0
                ? t("admin.export.integrityFailing")
                : preview
                  ? t("admin.export.integrityNotApplicable")
                  : t("admin.export.integrityHolds")}
          </span>
        </Cell>
        {/*
          S-5. §14.4 asks for "download history where permitted" and the table records one
          timestamp. Shown as the single fact it is, rather than presented as a history with one
          row — which would be a screen implying a record the system does not keep.
        */}
        <Cell label={t("admin.export.lastDownloaded")}>
          {view.downloaded_at ?? t("admin.export.neverDownloaded")}
        </Cell>
      </dl>

      {/*
        S-6, said on the screen rather than only in the plan. §14.4 lists a generator version and
        nothing in the system records one. An accountant comparing two exports that look different
        needs to know that this is not a question the platform can answer yet.
      */}
      <p className="mt-6 text-sm text-[var(--ink-600)]" data-testid="generator-version-absent">
        {t("admin.export.generatorVersionAbsent")}
      </p>
    </>
  );
}

/**
 * §14.3's state, translated, or the raw value when the platform returns one this screen has not
 * been taught. A blank cell would be the worst of the three: it would hide that anything is odd.
 */
function statusLabel(status: string): string {
  const key = statusLabelKey(status);
  return key === null ? status : t(key);
}

function Cell({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div>
      <dt className="text-sm text-[var(--ink-600)]">{label}</dt>
      <dd className="font-bold">{children}</dd>
    </div>
  );
}
