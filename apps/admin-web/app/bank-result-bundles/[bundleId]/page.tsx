"use client";

import { t, toPersianDigits } from "@gold/localization";
import { StateView } from "@gold/ui";
import { use, useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../components/admin-shell";
import { PagePreview } from "../../../components/page-preview";
import {
  attachExternalEvidence,
  type BundleDetail,
  createCrop,
  type CropRequest,
  isPreviewable,
  type ManualFields,
  readBundle,
  rotateAnticlockwise,
  rotateClockwise,
  type Rotation,
  stepPage,
} from "../../../src/bundles";

/**
 * The bank-result review workspace. §16.3 of the implementation plan.
 *
 * **Seven of §16.3's eleven items are here and four are deliberately not.** Attempt search, the
 * candidate drawer, the evidence drawer and the history drawer each need a route that does not
 * exist: `GET /api/v1/payment-attempts` (doc 05 `:1553`) is specified and unbuilt, and matching,
 * evidence links and segment history are M9's. Building four panels with nothing behind them would
 * put an operator in front of controls that cannot answer — worse than an absence, because an empty
 * drawer reads as "no candidates" rather than "this does not work yet".
 *
 * `tests/…/workspace-screens.test.ts` records those four against the OpenAPI contract, so the day
 * M9 adds one of those routes the test fails and says a panel is now buildable. The M7 screens plan
 * set that precedent with `RECORDED_AS_ABSENT`; this is the same shape with a live check attached.
 *
 * **The preview is the source of truth about its own size.** Every crop coordinate is normalised
 * against the `X-Preview-Pixel-*` headers of the image actually displayed, never against
 * `naturalWidth` and never against a bounding box. The server refuses a mismatch, so the failure
 * mode of getting it wrong is a crop that is always rejected rather than a crop of the wrong region
 * — but it is still a screen that cannot work, and this is the line that makes it work.
 *
 * **The external-evidence fallback is always offered**, not revealed when a preview fails. §16
 * `:1069` requires a bundle nothing can render to stay workable, and the case that matters most is
 * the preview that silently produces something useless rather than the one that errors.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly view: BundleDetail }
  | { readonly kind: "forbidden" }
  | { readonly kind: "missing" }
  | { readonly kind: "failed" };

export default function BankResultBundlePage({
  params,
}: {
  params: Promise<{ bundleId: string }>;
}) {
  const { bundleId } = use(params);
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [rotation, setRotation] = useState<Rotation>(0);
  const [fields, setFields] = useState<ManualFields>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const phaseForError = (error: unknown): Phase => {
    const status = (error as { status?: number }).status;
    if (status === 403) return { kind: "forbidden" };
    if (status === 404) return { kind: "missing" };
    return { kind: "failed" };
  };

  const load = useCallback(
    () =>
      readBundle(bundleId)
        .then((view) => {
          setPhase({ kind: "ready", view });
          setSelectedFileId((current) => current ?? view.files.find(isPreviewable)?.id ?? null);
        })
        .catch((error: unknown) => setPhase(phaseForError(error))),
    [bundleId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const detail = phase.kind === "ready" ? phase.view : null;
  const selected = detail?.files.find((file) => file.id === selectedFileId) ?? null;

  const submitCrop = async (request: CropRequest) => {
    setBusy(true);
    setNotice(null);
    try {
      await createCrop(bundleId, request);
      setNotice(t("admin.workspace.cropAccepted"));
      await load();
    } catch {
      setNotice(t("admin.workspace.cropFailed"));
    } finally {
      setBusy(false);
    }
  };

  const submitExternal = async () => {
    if (!selected) return;
    setBusy(true);
    setNotice(null);
    try {
      await attachExternalEvidence(bundleId, selected.file_id, selected.id, fields);
      setNotice(t("admin.workspace.externalAccepted"));
      await load();
    } catch {
      setNotice(t("admin.workspace.externalFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AdminShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("admin.workspace.title")}</h1>

        {phase.kind === "loading" ? (
          <StateView
            description={t("admin.workspace.loading")}
            headingLevel={2}
            kind="loading"
            title={t("admin.workspace.loading")}
          />
        ) : null}

        {phase.kind === "forbidden" ? (
          <StateView
            description={t("admin.workspace.forbidden")}
            headingLevel={2}
            kind="forbidden"
            title={t("admin.workspace.forbiddenTitle")}
          />
        ) : null}

        {phase.kind === "missing" ? (
          <StateView
            description={t("admin.workspace.missing")}
            headingLevel={2}
            kind="empty"
            title={t("admin.workspace.missingTitle")}
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
            description={t("admin.workspace.failed")}
            headingLevel={2}
            kind="error"
            title={t("admin.workspace.failedTitle")}
          />
        ) : null}

        {detail ? (
          <div className="mt-6 flex flex-col gap-6">
            {/* §16.3's "bundle summary and unresolved navigation". */}
            <section aria-labelledby="bundle-summary">
              <h2 className="text-xl font-bold" id="bundle-summary">
                {t("admin.workspace.summary")}
              </h2>
              <dl className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3">
                <Fact label={t("admin.workspace.reference")} value={detail.bundle_number} />
                <Fact label={t("admin.workspace.state")} value={detail.status} />
                <Fact label={t("admin.workspace.sourceType")} value={detail.source_type} />
                <Fact
                  label={t("admin.workspace.segments")}
                  value={toPersianDigits(String(detail.segment_count))}
                />
                <Fact
                  label={t("admin.workspace.resolved")}
                  value={toPersianDigits(String(detail.resolved_segment_count))}
                />
                <Fact
                  label={t("admin.workspace.unresolved")}
                  value={toPersianDigits(String(detail.unresolved_segment_count))}
                />
              </dl>
              <p className="mt-2 text-sm text-[var(--muted)]">
                {detail.unresolved_segment_count === 0
                  ? t("admin.workspace.noUnresolved")
                  : t("admin.workspace.gotoUnresolved")}
              </p>
            </section>

            {/* §16.3's file selection, and the "Excel preview" item's honest answer. */}
            <section aria-labelledby="bundle-files">
              <h2 className="text-xl font-bold" id="bundle-files">
                {t("admin.workspace.files")}
              </h2>
              <ul className="mt-3 flex flex-wrap gap-2">
                {detail.files.map((file) => (
                  <li key={file.id}>
                    <button
                      aria-current={file.id === selectedFileId}
                      className="rounded-lg border border-[var(--border)] px-3 py-2 font-bold aria-[current=true]:bg-[var(--surface-sunken)]"
                      onClick={() => {
                        setSelectedFileId(file.id);
                        setPageNumber(1);
                        setRotation(0);
                      }}
                      type="button"
                    >
                      {file.file_name}
                    </button>
                  </li>
                ))}
              </ul>
            </section>

            {selected && !isPreviewable(selected) ? (
              <StateView
                description={t("admin.workspace.noPreviewExplanation")}
                headingLevel={2}
                kind="empty"
                title={t("admin.workspace.noPreview")}
              />
            ) : null}

            {selected && isPreviewable(selected) ? (
              <section aria-labelledby="bundle-preview" className="flex flex-col gap-4">
                <h2 className="text-xl font-bold" id="bundle-preview">
                  {t("admin.workspace.crop")}
                </h2>

                {/* §16.3's "page selection" and "rotation". */}
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    className="rounded-lg border border-[var(--border)] px-3 py-1 font-bold"
                    onClick={() => setPageNumber((n) => stepPage(n, -1, selected.page_count))}
                    type="button"
                  >
                    {t("admin.workspace.previousPage")}
                  </button>
                  <span className="text-sm">
                    {t("admin.workspace.page")} {toPersianDigits(String(pageNumber))}{" "}
                    {t("admin.workspace.ofPages")}{" "}
                    {toPersianDigits(String(selected.page_count ?? 1))}
                  </span>
                  <button
                    className="rounded-lg border border-[var(--border)] px-3 py-1 font-bold"
                    onClick={() => setPageNumber((n) => stepPage(n, 1, selected.page_count))}
                    type="button"
                  >
                    {t("admin.workspace.nextPage")}
                  </button>
                  <button
                    className="rounded-lg border border-[var(--border)] px-3 py-1 font-bold"
                    onClick={() => setRotation(rotateAnticlockwise)}
                    type="button"
                  >
                    {t("admin.workspace.rotateAnticlockwise")}
                  </button>
                  <button
                    className="rounded-lg border border-[var(--border)] px-3 py-1 font-bold"
                    onClick={() => setRotation(rotateClockwise)}
                    type="button"
                  >
                    {t("admin.workspace.rotateClockwise")}
                  </button>
                  <span className="text-sm text-[var(--muted)]">
                    {t("admin.workspace.rotation")}: {toPersianDigits(String(rotation))}°
                  </span>
                </div>

                {/* Keyed on the page being looked at, so a change of file, page or angle is a
                    remount rather than an effect clearing state. See `PagePreview`. */}
                <PagePreview
                  bundleFile={selected}
                  busy={busy}
                  fields={fields}
                  key={`${selected.id}:${pageNumber}:${rotation}`}
                  onCrop={(request) => void submitCrop(request)}
                  pageNumber={pageNumber}
                  rotation={rotation}
                />
              </section>
            ) : null}

            {/* §16.3's "selected-segment fields". */}
            <FieldsForm fields={fields} onChange={setFields} />

            {/* §16.3's "external evidence fallback", always reachable. */}
            {selected ? (
              <section aria-labelledby="external-evidence">
                <h2 className="text-xl font-bold" id="external-evidence">
                  {t("admin.workspace.external")}
                </h2>
                <p className="mt-2 text-sm text-[var(--muted)]">
                  {t("admin.workspace.externalExplanation")}
                </p>
                <button
                  className="mt-3 rounded-lg border border-[var(--border)] px-4 py-2 font-bold disabled:opacity-60"
                  disabled={busy}
                  onClick={() => void submitExternal()}
                  type="button"
                >
                  {t("admin.workspace.externalConfirm")}
                </button>
              </section>
            ) : null}

            {notice ? (
              <p aria-live="polite" className="rounded-lg bg-[var(--surface-sunken)] px-4 py-3">
                {notice}
              </p>
            ) : null}
          </div>
        ) : null}
      </section>
    </AdminShell>
  );
}

function Fact({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="rounded-lg bg-[var(--surface-sunken)] px-3 py-2">
      <dt className="text-sm text-[var(--muted)]">{label}</dt>
      <dd className="font-bold">{value}</dd>
    </div>
  );
}

function FieldsForm({
  fields,
  onChange,
}: {
  readonly fields: ManualFields;
  readonly onChange: (next: ManualFields) => void;
}) {
  return (
    <section aria-labelledby="segment-fields">
      <h2 className="text-xl font-bold" id="segment-fields">
        {t("admin.workspace.fields")}
      </h2>
      <p className="mt-2 text-sm text-[var(--muted)]">{t("admin.workspace.fieldsOptional")}</p>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <TextField
          label={t("admin.workspace.beneficiary")}
          onChange={(value) => onChange({ ...fields, beneficiary_name: value })}
          value={fields.beneficiary_name ?? ""}
        />
        <TextField
          label={t("admin.workspace.iban")}
          onChange={(value) => onChange({ ...fields, destination_iban: value })}
          value={fields.destination_iban ?? ""}
        />
        {/* A text input, not `type="number"`. An IRR amount can exceed `Number.MAX_SAFE_INTEGER`,
            and a browser number field would round it before anybody saw it. */}
        <TextField
          label={t("admin.workspace.amount")}
          onChange={(value) => onChange({ ...fields, amount_irr: value })}
          value={fields.amount_irr ?? ""}
        />
        <TextField
          label={t("admin.workspace.tracking")}
          onChange={(value) => onChange({ ...fields, tracking_number: value })}
          value={fields.tracking_number ?? ""}
        />
      </div>
    </section>
  );
}

function TextField({
  label,
  value,
  onChange,
}: {
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm font-bold">
      {label}
      <input
        className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
        onChange={(event) => onChange(event.target.value)}
        type="text"
        value={value}
      />
    </label>
  );
}
