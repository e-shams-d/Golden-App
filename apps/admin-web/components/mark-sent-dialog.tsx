"use client";

import { t, toPersianDigits } from "@gold/localization";
import { useState } from "react";

import {
  type ExportDetail,
  markSentToBank,
  splitCheck,
} from "../src/bank-exports";

/**
 * §14.7. The confirmation, and the claim it records.
 *
 * **All ten of §14.7's fields are shown before the command is sent.** `UI-SENT-001`, and the reason
 * is the word "confirmation": a dialog that said "mark as sent?" with a Yes button would be asking
 * somebody to confirm a decision they cannot see. The ten fields are what identify *which file*,
 * and this is the last moment identifying it changes anything.
 *
 * **The command targets `view.id` and nothing else.** `UI-SENT-003`. This component receives the
 * export and never a batch, so there is no batch id in scope to send by mistake —
 * `15_Agent_Implementation_Plan.md:978`: it "acts on an exact `BankExcelExport`, not a generic
 * batch". A batch may have had several versions and several exports; exactly one was uploaded.
 *
 * **Nothing here contacts a bank.** §15.7 makes submission manual by design, so this records a
 * claim a person makes — which is why it captures the channel they used and what they said about
 * it. The record has to be enough for somebody else to check the claim later.
 */

/**
 * The channels §15.7 leaves to a person, each with its label.
 *
 * A map rather than a list plus a template key, for the reason `EXPORT_STATUS_LABELS` gives: a
 * channel added without a message would typecheck behind a cast and render an empty option. The
 * server takes any string up to 64 characters, so this list is the screen's choice — free text
 * would make "how do we usually send these" an unanswerable question six months from now.
 */
const CHANNELS = {
  bank_portal_manual_upload: "admin.export.channel.bank_portal_manual_upload",
  bank_branch_in_person: "admin.export.channel.bank_branch_in_person",
  secure_email_to_bank: "admin.export.channel.secure_email_to_bank",
} as const;

const DEFAULT_CHANNEL = "bank_portal_manual_upload";

export function MarkSentDialog({
  onCancel,
  onDone,
  view,
}: {
  readonly onCancel: () => void;
  readonly onDone: () => void;
  /** The export, and only the export. There is no batch in scope to target by accident. */
  readonly view: ExportDetail;
}) {
  const [channel, setChannel] = useState<keyof typeof CHANNELS>(DEFAULT_CHANNEL);
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setBusy(true);
    setError(null);
    void markSentToBank({
      exportId: view.id,
      // The moment the person says they sent it, which is now. §14.7 lists "sent time" and the
      // server records it as given — a claim about the past, not a server clock reading.
      sentAt: new Date().toISOString(),
      submissionChannel: channel,
      note: note.trim() === "" ? null : note.trim(),
      idempotencyKey: crypto.randomUUID(),
    })
      .then(() => {
        // Only after the server has recorded it. The parent reloads and the screen says so because
        // the API says so, not because this dialog assumed it.
        onDone();
      })
      .catch((caught: unknown) => {
        const message = (caught as { body?: { error?: { message?: string } } }).body?.error?.message;
        setError(message ?? t("admin.export.markSentFailed"));
      })
      .finally(() => setBusy(false));
  };

  return (
    <div
      aria-labelledby="mark-sent-title"
      aria-modal="true"
      className="mt-5 rounded-2xl border-2 border-[var(--gold-700)] bg-[var(--surface)] p-5"
      data-testid="mark-sent-dialog"
      role="dialog"
    >
      <h2 className="text-2xl font-black" id="mark-sent-title">
        {t("admin.export.markSentTitle")}
      </h2>
      <p className="mt-2 leading-8 text-[var(--ink-600)]">{t("admin.export.markSentBody")}</p>

      {/* §14.7's ten, shown before anything is sent. `UI-SENT-001`. */}
      <dl
        className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 rounded-xl bg-[var(--surface-subtle)] p-4"
        data-testid="mark-sent-summary"
      >
        <Row label={t("admin.export.reference")}>{view.export_number}</Row>
        <Row label={t("admin.export.fileName")}>
          <span dir="ltr">{view.file_name}</span>
        </Row>
        <Row label={t("admin.export.batchAndVersion")}>
          {view.batch_number} — {toPersianDigits(String(view.version_number))}
        </Row>
        <Row label={t("admin.export.checksumAndIntegrity")}>
          <code dir="ltr" title={view.file_sha256_hash}>
            {view.file_sha256_hash.slice(0, 12)}
          </code>
          {" — "}
          {view.integrity_failed_checks.length === 0
            ? t("admin.export.integrityHolds")
            : splitCheck(view.integrity_failed_checks[0]!).name}
        </Row>
        <Row label={t("admin.export.rowCount")}>{toPersianDigits(String(view.row_count))}</Row>
        <Row label={t("admin.export.total")}>{toPersianDigits(view.total_amount_irr)}</Row>
        <Row label={t("admin.export.bankAndSourceAccount")}>
          {view.bank ?? t("common.unknown")} — {view.source_account ?? t("common.unknown")}
        </Row>
        {/* The remaining three — channel, sent time and note — are the ones being *supplied*, so
            they appear as the controls below rather than as read-only rows. §14.7 lists them among
            what the confirmation shows, and a field somebody is filling in is shown by being
            editable. */}
      </dl>

      <label className="mt-4 block">
        <span className="font-bold">{t("admin.export.channelLabel")}</span>
        <select
          className="mt-1 w-full rounded-lg border border-[var(--border)] p-2"
          data-testid="submission-channel"
          disabled={busy}
          onChange={(event) => setChannel(event.target.value as keyof typeof CHANNELS)}
          value={channel}
        >
          {Object.entries(CHANNELS).map(([value, key]) => (
            <option key={value} value={value}>
              {t(key)}
            </option>
          ))}
        </select>
      </label>

      <label className="mt-4 block">
        <span className="font-bold">{t("admin.export.noteLabel")}</span>
        <textarea
          className="mt-1 w-full rounded-lg border border-[var(--border)] p-2"
          data-testid="mark-sent-note"
          disabled={busy}
          onChange={(event) => setNote(event.target.value)}
          rows={3}
          value={note}
        />
      </label>

      <label className="mt-4 flex items-start gap-2">
        <input
          checked={confirmed}
          data-testid="mark-sent-confirm"
          disabled={busy}
          onChange={(event) => setConfirmed(event.target.checked)}
          type="checkbox"
        />
        {/* The claim, stated as a claim. Somebody ticking this is asserting a fact about the world
            that the platform cannot check, and the wording should make that plain. */}
        <span>{t("admin.export.markSentAffirmation")}</span>
      </label>

      {error ? (
        <p
          className="mt-4 rounded-lg border border-[var(--danger-600)] bg-[var(--danger-50)] p-3"
          data-testid="mark-sent-error"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <div className="mt-5 flex flex-wrap gap-3">
        <button
          className="rounded-lg bg-[var(--gold-700)] px-4 py-2 font-bold text-white disabled:opacity-50"
          data-testid="mark-sent-submit"
          disabled={busy || !confirmed}
          onClick={submit}
          type="button"
        >
          {busy ? t("admin.export.markSentWorking") : t("admin.export.markSentSubmit")}
        </button>
        <button
          className="rounded-lg border border-[var(--border)] px-4 py-2 font-bold"
          disabled={busy}
          onClick={onCancel}
          type="button"
        >
          {t("common.cancel")}
        </button>
      </div>
    </div>
  );
}

function Row({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div>
      <dt className="text-sm text-[var(--ink-600)]">{label}</dt>
      <dd className="font-bold">{children}</dd>
    </div>
  );
}
