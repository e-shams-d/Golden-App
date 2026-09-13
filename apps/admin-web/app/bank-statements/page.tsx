"use client";

import { stateForError } from "@gold/api-client";
import { t } from "@gold/localization";
import { BidiText, StateView, kindForApplicationState } from "@gold/ui";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../components/admin-shell";
import { listBankAccounts, listBankProfiles, readBankProfile } from "../../src/bank-configuration";
import {
  createBankStatement,
  listBankStatements,
  uploadStatementFile,
  STATEMENT_LIMITS,
  type BankStatement,
} from "../../src/bank-statements";
import type { BankAccount, BankProfileVersion } from "../../src/bank-configuration";

/**
 * The bank's own account of what moved, filed so it can be parsed and matched.
 *
 * M0 slice D. Five operations M10 built and no screen reached — and the reason recorded against
 * them in `NO_SCREEN` was wrong. It said the path was "blocked on the bank", which returns no
 * Excel. **The real blocker was that an import run requires an active bank mapping and nothing
 * could produce one**: the two routes that would let an operator supply one are catalogued and
 * never served. A real file would not have helped.
 *
 * The owner decided on 2026-09-13 that the mapping is a single fixed function in code — the file
 * we expect *is* the input — and activating a bank-profile version writes it, so this screen never
 * mentions it. **That is also why the version choice below matters more than it looks**: a version
 * nobody activated has no mapping, and a statement filed against one cannot be parsed.
 *
 * **Filing a statement needs three things the operator must not have to type.** The account it
 * belongs to and the configuration in force are both ids; M0 slice B made both readable, which is
 * why this screen can offer them as choices rather than as fields. The bytes come from an upload.
 *
 * **The date range is both or neither.** §8.1 makes it optional and the command refuses a half, so
 * the button stays disabled until it is whole — an operator is told before a round trip rather
 * than after.
 */

type Phase =
  | { readonly kind: "loading" }
  | {
      readonly kind: "ready";
      readonly statements: readonly BankStatement[];
      readonly accounts: readonly BankAccount[];
      readonly versions: readonly BankProfileVersion[];
    }
  | { readonly kind: "state"; readonly state: string };

export default function BankStatementsPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [uploadedFileId, setUploadedFileId] = useState<string | null>(null);
  const [form, setForm] = useState({
    bankProfileVersionId: "",
    bankAccountId: "",
    dateRangeStart: "",
    dateRangeEnd: "",
  });

  const load = useCallback(async (signal?: AbortSignal): Promise<Phase> => {
    const statements = await listBankStatements(signal);
    const accounts = await listBankAccounts(signal);
    // Every profile's versions, so the operator picks the configuration that was in force when the
    // bank produced this statement rather than whichever is in force now. A statement filed
    // against today's rules would be parsed by rules the bank was not using.
    const profiles = await listBankProfiles(signal);
    const versions: BankProfileVersion[] = [];
    for (const profile of profiles) {
      versions.push(...(await readBankProfile(profile.id, signal)).versions);
    }
    return { kind: "ready", statements, accounts, versions };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((next) => setPhase(next))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const state = stateForError(error);
        if (state !== undefined) setPhase({ kind: "state", state });
      });
    return () => controller.abort();
  }, [load]);

  const act = (run: () => Promise<unknown>) => {
    setBusy(true);
    setNotice(null);
    void run()
      .then(async () => {
        setPhase(await load());
      })
      .catch(async (caught: unknown) => {
        const message = (caught as { body?: { error?: { message?: string } } }).body?.error
          ?.message;
        setNotice(message ?? t("statement.failed"));
        try {
          setPhase(await load());
        } catch {
          /* the notice carries it */
        }
      })
      .finally(() => setBusy(false));
  };

  const rangeIsWhole =
    (form.dateRangeStart.trim() === "") === (form.dateRangeEnd.trim() === "");

  return (
    <AdminShell>
      <section aria-labelledby="statements-heading" className="space-y-6">
        <h1 className="text-xl font-semibold" id="statements-heading">
          {t("statement.title")}
        </h1>

        {phase.kind === "loading" ? (
          <StateView
            description={t("state.loading.description")}
            headingLevel={2}
            kind="loading"
            title={t("state.loading.title")}
          />
        ) : null}

        {phase.kind === "state" ? (
          <StateView
            description={t("statement.failed")}
            headingLevel={2}
            kind={kindForApplicationState(phase.state)}
            title={t("statement.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            {notice !== null ? (
              <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
                {notice}
              </p>
            ) : null}

            {phase.statements.length === 0 ? (
              <StateView
                description={t("statement.noneDescription")}
                headingLevel={2}
                kind="empty"
                title={t("statement.noneTitle")}
              />
            ) : (
              <ul className="space-y-2" data-testid="statement-list">
                {phase.statements.map((statement) => (
                  <li className="rounded border p-3 text-sm" key={statement.id}>
                    <Link
                      className="font-medium underline"
                      href={`/bank-statements/${statement.id}`}
                    >
                      <BidiText>{statement.created_at}</BidiText>
                    </Link>
                    <span className="ms-3">
                      <BidiText>{statement.status}</BidiText>
                    </span>
                    <span className="ms-3 text-[var(--ink-600)]">
                      <BidiText>
                        {statement.date_range_start === null
                          ? t("statement.noRange")
                          : `${statement.date_range_start} — ${statement.date_range_end}`}
                      </BidiText>
                    </span>
                  </li>
                ))}
              </ul>
            )}

            <section
              aria-labelledby="statement-new-heading"
              className="space-y-3 rounded border p-4"
            >
              <h2 className="text-lg font-semibold" id="statement-new-heading">
                {t("statement.fileNew")}
              </h2>

              {/* Says what shape is expected, because the mapping is fixed and a file that does
                  not match will fail the parse rather than being converted. That is the owner's
                  decision of 2026-09-13 stated where somebody is about to act on it. */}
              <p className="text-sm text-[var(--ink-600)]">{t("statement.expectedShape")}</p>

              {phase.versions.length === 0 || phase.accounts.length === 0 ? (
                // The state a fresh deployment is in: no bank configured, so no mapping was seeded
                // and nothing here can work. Said plainly with the way out, rather than letting
                // the operator fill a form that cannot submit.
                <StateView
                  description={t("statement.configureBankFirst")}
                  headingLevel={3}
                  kind="empty"
                  title={t("statement.configureBankFirstTitle")}
                />
              ) : (
                <>
                  <label className="block text-sm">
                    <span className="font-medium">{t("statement.account")}</span>
                    <select
                      className="mt-1 w-full rounded border p-2"
                      data-testid="statement-account"
                      disabled={busy}
                      onChange={(event) =>
                        setForm({ ...form, bankAccountId: event.target.value })
                      }
                      value={form.bankAccountId}
                    >
                      <option value="">{t("statement.chooseAccount")}</option>
                      {phase.accounts.map((account) => (
                        <option key={account.id} value={account.id}>
                          {account.display_name}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="block text-sm">
                    <span className="font-medium">{t("statement.version")}</span>
                    <select
                      className="mt-1 w-full rounded border p-2"
                      data-testid="statement-version"
                      disabled={busy}
                      onChange={(event) =>
                        setForm({ ...form, bankProfileVersionId: event.target.value })
                      }
                      value={form.bankProfileVersionId}
                    >
                      <option value="">{t("statement.chooseVersion")}</option>
                      {phase.versions.map((version) => (
                        <option key={version.id} value={version.id}>
                          {`${version.version_number} — ${version.status}`}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="block text-sm">
                    <span className="font-medium">{t("statement.rangeStart")}</span>
                    <input
                      className="mt-1 w-full rounded border p-2"
                      data-testid="statement-range-start"
                      disabled={busy}
                      onChange={(event) =>
                        setForm({ ...form, dateRangeStart: event.target.value })
                      }
                      type="date"
                      value={form.dateRangeStart}
                    />
                  </label>

                  <label className="block text-sm">
                    <span className="font-medium">{t("statement.rangeEnd")}</span>
                    <input
                      className="mt-1 w-full rounded border p-2"
                      data-testid="statement-range-end"
                      disabled={busy}
                      onChange={(event) => setForm({ ...form, dateRangeEnd: event.target.value })}
                      type="date"
                      value={form.dateRangeEnd}
                    />
                  </label>
                  {rangeIsWhole ? null : (
                    <p className="text-sm text-[var(--danger-600)]" role="alert">
                      {t("statement.rangeNeedsBoth")}
                    </p>
                  )}

                  <label className="block text-sm">
                    <span className="font-medium">{t("statement.file")}</span>
                    <input
                      accept=".xlsx,.csv"
                      className="mt-1 w-full rounded border p-2"
                      data-testid="statement-file"
                      disabled={busy}
                      onChange={(event) => {
                        const chosen = event.target.files?.[0];
                        if (!chosen) return;
                        if (chosen.size > STATEMENT_LIMITS.maxBytes) {
                          setNotice(t("statement.tooLarge"));
                          return;
                        }
                        setNotice(null);
                        setBusy(true);
                        void uploadStatementFile(chosen)
                          .then((fileId) => setUploadedFileId(fileId))
                          .catch(() => setNotice(t("statement.uploadFailed")))
                          .finally(() => setBusy(false));
                      }}
                      type="file"
                    />
                    <span className="text-[var(--ink-600)]">{t("statement.fileHint")}</span>
                  </label>
                  {uploadedFileId === null ? null : (
                    <p className="text-sm" data-testid="statement-file-ready">
                      {t("statement.fileReady")}
                    </p>
                  )}

                  <button
                    className="rounded border px-3 py-1 font-bold disabled:opacity-50"
                    data-testid="statement-create"
                    disabled={
                      busy ||
                      uploadedFileId === null ||
                      form.bankAccountId === "" ||
                      form.bankProfileVersionId === "" ||
                      !rangeIsWhole
                    }
                    onClick={() =>
                      act(async () => {
                        await createBankStatement({
                          bankProfileVersionId: form.bankProfileVersionId,
                          bankAccountId: form.bankAccountId,
                          originalFileId: uploadedFileId ?? "",
                          dateRangeStart: form.dateRangeStart,
                          dateRangeEnd: form.dateRangeEnd,
                        });
                        // The file belongs to the statement now; a second submit would file the
                        // same bytes twice under a new record.
                        setUploadedFileId(null);
                      })
                    }
                    type="button"
                  >
                    {t("statement.fileIt")}
                  </button>
                </>
              )}
            </section>
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}
