/**
 * The bank file, as the screen sees it. §14 of the screen specification.
 *
 * Per-app for `src/batches.ts`'s reason: `UI-ISO-001` requires that neither bundle contain the
 * other's endpoint paths, and an export has no trader-side counterpart at all.
 *
 * **Nothing here decides whether the file is sound.** `integrity_failed_checks` arrives evaluated
 * and `approval_hash_matches` arrives compared — slice 2B made both server-side deliberately,
 * because a screen recomputing either would be a second opinion about a rule the download path
 * enforces, and the two would eventually disagree about whether a payment file may be sent.
 *
 * **`sendable` is read, never derived.** A screen that decided sendability from `export_type` and
 * `status` would be re-implementing the rule that keeps a preview out of a bank, in the one place
 * where being wrong is a wrong payment. `FINANCIAL_INTEGRITY_BASELINE.md` §1 puts the prohibition
 * in the absence of an UPDATE grant on `export_type`; this module's job is to carry the answer.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** Every field §14.4 and §14.7 name, as slice 2B returns them. */
export type ExportDetail = Readonly<{
  id: string;
  export_number: string;
  export_type: string;
  status: string;
  sendable: boolean;
  awaiting_send_confirmation: boolean;
  row_count: number;
  total_amount_irr: string;
  content_hash: string;
  file_sha256_hash: string;
  payment_batch_version_id: string;
  batch_approval_id: string | null;
  generated_at: string;
  downloaded_at: string | null;
  sent_to_bank_marked_at: string | null;
  file_name: string;
  batch_id: string;
  batch_number: string;
  version_number: number;
  bank: string | null;
  bank_profile_version_number: number | null;
  mapping_version: number | null;
  source_account: string | null;
  approval_hash_matches: boolean | null;
  integrity_failed_checks: readonly string[];
  generated_by: string | null;
  sent_by: string | null;
}>;

export const EXPORT_PREVIEW = "preview";
export const EXPORT_QUARANTINED = "quarantined";

/**
 * §14.1's banner, character for character.
 *
 * **Not in `@gold/localization`, and that is the point.** Every other string this app shows is
 * Persian, because every other string is for a person to read in their own language. This one is a
 * *fixed marker*: §14.1 gives it inside a code block, which is how that document writes text that
 * must appear as written. A translated banner would be a paraphrase of a safety label, and
 * `apps/admin-web/test/export-screens.test.ts` parses the specification to hold this constant to
 * it — a check that cannot work against a translation.
 *
 * The screen renders this **and** a Persian explanation beside it. The verbatim marker is what the
 * document requires; the explanation is what makes it mean something to the accountant reading it.
 * Neither substitutes for the other.
 */
export const PREVIEW_BANNER = "PREVIEW — NOT APPROVED FOR BANK SUBMISSION";

/**
 * §14.6's sentence, character for character.
 *
 * `15_Agent_Implementation_Plan.md:989` makes this the milestone's central human-factors risk, and
 * the wording is the mitigation: an accountant who downloads a file, emails it to the bank and
 * forgets to come back leaves the system believing the payment was never made, and the next
 * reconciliation cycle chases a payment that already happened.
 *
 * Verbatim for `PREVIEW_BANNER`'s reason and one more. §14.6 says "The UI must clearly state" and
 * then gives the words — so a paraphrase is not a translation decision, it is dropping the
 * requirement. The Persian sentence beside it says the same thing for the person who has to act on
 * it; neither replaces the other.
 */
export const DOWNLOAD_IS_NOT_SENDING =
  "Downloading the file does not mean it was sent to the bank.";

/**
 * §14.3's states, mapped to their labels. All eight the catalogue has, and only those.
 *
 * A map rather than a template key, because `t(`admin.export.status.${status}`)` is not a checkable
 * call: a status the catalogue gains would render as a missing translation, which on this screen
 * means a bank file whose state is blank. `test/export-screens.test.ts` compares these keys against
 * `status_catalog.yaml`'s `bank_export` aggregate, so the drift fails a test rather than a render.
 *
 * §14.3 also names `requested` and `superseded`. Neither is here: `requested` has no row to render,
 * because an export exists only once its file does, and `superseded` is DOC-CONFLICT-016 with G-3
 * carrying the substantive half. Rendering a state the API can never return would be a screen
 * written against a document rather than against the system.
 */
export const EXPORT_STATUS_LABELS = {
  generating: "admin.export.status.generating",
  generated: "admin.export.status.generated",
  validated: "admin.export.status.validated",
  downloaded: "admin.export.status.downloaded",
  sent_to_bank_marked: "admin.export.status.sent_to_bank_marked",
  voided: "admin.export.status.voided",
  quarantined: "admin.export.status.quarantined",
  generation_failed: "admin.export.status.generation_failed",
} as const;

export type ExportStatus = keyof typeof EXPORT_STATUS_LABELS;

/**
 * The label for a status, or the status itself when it is one this screen does not know.
 *
 * The fallback shows the raw value rather than an empty cell. A blank state on a payment file is
 * the worst of the three options: a raw `superseded` at least tells whoever is looking that the
 * platform returned something the screen has not been taught.
 */
export function statusLabelKey(status: string): (typeof EXPORT_STATUS_LABELS)[ExportStatus] | null {
  return status in EXPORT_STATUS_LABELS
    ? EXPORT_STATUS_LABELS[status as ExportStatus]
    : null;
}

export async function readExport(exportId: string, signal?: AbortSignal): Promise<ExportDetail> {
  const response = await transport.request<ExportDetail>({
    method: "GET",
    path: `/bank-exports/${encodeURIComponent(exportId)}`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * The URL the download control points at. §14.6.
 *
 * A plain link rather than a fetch, deliberately: the response is a streamed spreadsheet with a
 * `Content-Disposition` filename, and a `fetch` would mean reading a payment file into memory and
 * re-inventing the save dialog. The server revalidates integrity on this path and answers `409`
 * when it fails — which the browser shows as a failed download, and the screen's next refresh
 * explains, because `status` will have moved to `quarantined`.
 *
 * **The export id, never the batch.** `15_Agent_Implementation_Plan.md:978`: mark-sent "acts on an
 * exact `BankExcelExport`, not a generic batch", and the same is true of taking the file — a batch
 * may have had several versions and several exports, and exactly one of them is the one somebody
 * uploads.
 */
export function downloadPath(exportId: string): string {
  return `/api/v1/bank-exports/${encodeURIComponent(exportId)}/download`;
}

/**
 * Record that a person uploaded this exact file. §14.7's command.
 *
 * `exportId` is the only target this takes. `UI-SENT-003` exists because a screen holding both a
 * batch and an export in scope is one careless edit from sending the batch id, and the server would
 * answer `404` rather than doing something wrong — but a `404` on this command reads as "the file is
 * gone", which is the most alarming possible way to report a typo.
 */
export async function markSentToBank(input: {
  exportId: string;
  sentAt: string;
  submissionChannel: string;
  note: string | null;
  idempotencyKey: string;
  signal?: AbortSignal;
}): Promise<MarkSentConfirmation> {
  const response = await transport.request<MarkSentConfirmation>({
    method: "POST",
    path: `/bank-exports/${encodeURIComponent(input.exportId)}/mark-sent-to-bank`,
    body: {
      sent_at: input.sentAt,
      submission_channel: input.submissionChannel,
      note: input.note,
    },
    idempotencyKey: input.idempotencyKey,
    ...(input.signal ? { signal: input.signal } : {}),
  });
  return response.data;
}

/**
 * §14.7's confirmation. Everything `ExportDetail` carries, plus the two values no table stores.
 *
 * Slice 2B's asymmetry: §11.8 gives `bank_excel_exports` no column for the channel or the note, so
 * the command's own response is the only place they can be shown honestly. A screen that expected
 * to re-read them later would be asking for a column to be invented.
 */
export type MarkSentConfirmation = ExportDetail &
  Readonly<{
    submission_channel: string;
    note: string | null;
  }>;

/**
 * Whether this export is downloaded and still unconfirmed. `UI-SENT-002`.
 *
 * **Read, not derived.** The obvious client-side version is
 * `downloaded_at !== null && sent_to_bank_marked_at === null`, and it is wrong in a way that would
 * not show up in testing: it ignores `export_type`, so a downloaded preview would grow a reminder
 * to confirm sending a file nobody may send. The server derives this from three values and
 * `SVC-SENT-002` is the obligation; this function's whole job is to not have an opinion.
 */
export function isAwaitingSendConfirmation(view: ExportDetail): boolean {
  return view.awaiting_send_confirmation;
}

/**
 * Whether this is a preview. §14.1's trigger, and read from the field the server cannot rewrite.
 *
 * `export_type` has no UPDATE grant in any migration, which is what makes "permanently
 * identifiable as non-sendable" (`15_Agent_Implementation_Plan.md:936`) true of the data rather
 * than of a rule somebody remembers. So this is the value to branch on, and `status` is not.
 */
export function isPreview(view: ExportDetail): boolean {
  return view.export_type === EXPORT_PREVIEW;
}

/** Whether §14.5 applies: the file disagrees with the record, so nothing may leave. */
export function isQuarantined(view: ExportDetail): boolean {
  return view.status === EXPORT_QUARANTINED;
}

/**
 * One failed check, split into the comparison's name and what disagreed.
 *
 * The server sends `"<check_name>: expected X, found Y"` — `IntegrityFailure.describe()`. Split
 * rather than reformatted: the check names are §15.5's own words and an operator reading
 * `export_content_hash_matches_version` in a bug report should find the same string on the screen.
 * A prettified "Content hash mismatch" would be a third spelling of a comparison that already has
 * two places to be spelled.
 */
export function splitCheck(described: string): { name: string; detail: string } {
  const separator = described.indexOf(": ");
  if (separator === -1) return { name: described, detail: "" };
  return {
    name: described.slice(0, separator),
    detail: described.slice(separator + 2),
  };
}
