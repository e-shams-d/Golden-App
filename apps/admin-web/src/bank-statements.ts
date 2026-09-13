/**
 * Bank statements and the runs that parse them.
 *
 * M0 slice D. Five operations M10 built and no screen reached, and the reason recorded against
 * them was wrong: `NO_SCREEN` said the path was "blocked on the bank", which returns no Excel. The
 * real blocker was that **an import run requires an active bank mapping and nothing could produce
 * one** — the two routes that would let an operator supply it are catalogued and never served. Even
 * a real file would not have started this flow.
 *
 * The owner decided on 2026-09-13 that the mapping is a single fixed function in code, written
 * against a bank-profile version when that version is activated, so `bank_mapping_id` is optional on
 * the wire and this module never sends one. A client that named it would be holding a copy of a
 * value the server derives from the statement itself.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** A `crypto.randomUUID()` per command, like every other data module here. */
const commandKey = (): string => crypto.randomUUID();

export type BankStatement = Readonly<{
  id: string;
  bank_profile_version_id: string;
  bank_account_id: string;
  original_file_id: string;
  status: string;
  date_range_start: string | null;
  date_range_end: string | null;
  record_version: number;
  created_at: string;
}>;

/**
 * One attempt to parse a statement.
 *
 * `row_count` is `null` until a run finishes, and that is deliberate on the server's side: zero
 * would say it parsed and found none. The screen renders the difference rather than collapsing it.
 */
export type StatementImportRun = Readonly<{
  id: string;
  bank_statement_file_id: string;
  bank_mapping_id: string;
  run_number: number;
  status: string;
  row_count: number | null;
  parser_version: string;
  source_hash: string;
  started_at: string | null;
  finished_at: string | null;
  error_summary: Record<string, unknown> | null;
  created_at: string;
}>;

export async function listBankStatements(signal?: AbortSignal): Promise<readonly BankStatement[]> {
  const response = await transport.request<readonly BankStatement[]>({
    method: "GET",
    path: "/bank-statements",
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

export async function readBankStatement(
  statementId: string,
  signal?: AbortSignal,
): Promise<BankStatement> {
  const response = await transport.request<BankStatement>({
    method: "GET",
    path: `/bank-statements/${encodeURIComponent(statementId)}`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

export async function listImportRuns(
  statementId: string,
  signal?: AbortSignal,
): Promise<readonly StatementImportRun[]> {
  const response = await transport.request<readonly StatementImportRun[]>({
    method: "GET",
    path: `/bank-statements/${encodeURIComponent(statementId)}/import-runs`,
    ...(signal ? { signal } : {}),
  });
  return response.data;
}

/**
 * File the bank's statement: which account it belongs to, which configuration was in force, and
 * the uploaded bytes.
 *
 * **The date range is both or neither.** §8.1 makes it optional and the command refuses a half —
 * the screen enforces it too, so the operator is told which end is missing before a round trip
 * rather than after.
 */
export async function createBankStatement(
  input: Readonly<{
    bankProfileVersionId: string;
    bankAccountId: string;
    originalFileId: string;
    dateRangeStart?: string;
    dateRangeEnd?: string;
  }>,
): Promise<BankStatement> {
  const response = await transport.request<BankStatement, Record<string, unknown>>({
    method: "POST",
    path: "/bank-statements",
    body: {
      bank_profile_version_id: input.bankProfileVersionId,
      bank_account_id: input.bankAccountId,
      original_file_id: input.originalFileId,
      date_range_start: input.dateRangeStart?.trim() ? input.dateRangeStart : null,
      date_range_end: input.dateRangeEnd?.trim() ? input.dateRangeEnd : null,
    },
    idempotencyKey: commandKey(),
  });
  return response.data;
}

/**
 * Start a parse. Answers **202**, not 201: the run exists and nothing has been read yet.
 *
 * **No `bank_mapping_id`.** There is one mapping, defined in `app/statements/expected_file.py` and
 * chosen by the server. Sending one from here would be this application holding a copy of a value
 * it cannot verify — and a stale copy would aim a run at a mapping that no longer exists.
 */
export async function startImportRun(statementId: string): Promise<StatementImportRun> {
  const response = await transport.request<StatementImportRun, Record<string, unknown>>({
    method: "POST",
    path: `/bank-statements/${encodeURIComponent(statementId)}/import-runs`,
    body: {},
    idempotencyKey: commandKey(),
  });
  return response.data;
}

/**
 * What `bank_statement` accepts, as `app/files/purposes.py:115` states it.
 *
 * **Constants here only until a limits endpoint exists**, which is the same compromise
 * `trader-pwa/src/evidence.ts` documents for the receipt purpose: hard-coding POL-006's numbers
 * puts them in the bundle, and changing a limit then needs a frontend release. The panel takes
 * them as props either way, so that endpoint changes one line.
 */
export const STATEMENT_LIMITS = {
  acceptedMediaTypes: [
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
  ] as const,
  maxBytes: 25 * 1024 * 1024,
} as const;

/**
 * Upload the statement bytes and hand back the file id the record needs.
 *
 * **The purpose is fixed here rather than chosen by the screen**, for the reason `evidence.ts`
 * gives about the receipt upload: a screen that could name a purpose could ask for one it has no
 * business using, and the purpose is what decides visibility and the ceiling.
 */
export async function uploadStatementFile(file: File, signal?: AbortSignal): Promise<string> {
  const body = new FormData();
  body.append("purpose", "bank_statement");
  body.append("file", file, file.name);

  const response = await transport.request<{ id: string }, FormData>({
    method: "POST",
    path: "/files",
    body,
    idempotencyKey: commandKey(),
    ...(signal ? { signal } : {}),
  });
  return response.data.id;
}
