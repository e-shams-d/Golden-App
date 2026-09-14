"use client";

import { stateForError } from "@gold/api-client";
import { t } from "@gold/localization";
import { BidiText, StateView, kindForApplicationState } from "@gold/ui";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../components/admin-shell";
import {
  listImportRuns,
  readBankStatement,
  startImportRun,
  type BankStatement,
  type StatementImportRun,
} from "../../../src/bank-statements";

/**
 * One statement, and every attempt to read it.
 *
 * M0 slice D. **The history is the screen**, not a detail of it. `04_Database_Schema.md:774` makes
 * a reparse a new run, document 08 §8.2 states the consequence — "Reprocessing never overwrites
 * earlier rows" — and an operator with no way to see run 1 beside run 2 has to take that on trust.
 * That is why `listImportRuns` exists at all: §21.4 does not list it among its five routes, and M10
 * added it for exactly this reason.
 *
 * **`row_count` renders `null` and zero differently.** Null is "this run has not finished"; zero is
 * "it finished and the file had no rows". Collapsing them would tell an operator their statement was
 * empty when the parse had not started.
 *
 * **No mapping is chosen here.** The owner decided on 2026-09-13 that there is one fixed mapping in
 * code, resolved from the statement's own bank-profile version. A dropdown would be a question with
 * one answer, and a wrong answer would parse the bank's columns in the wrong places.
 */

type Phase =
  | { readonly kind: "loading" }
  | {
      readonly kind: "ready";
      readonly statement: BankStatement;
      readonly runs: readonly StatementImportRun[];
    }
  | { readonly kind: "state"; readonly state: string };

export default function BankStatementPage({
  params,
}: {
  params: Promise<{ statementId: string }>;
}) {
  const { statementId } = use(params);
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal): Promise<Phase> => ({
      kind: "ready",
      statement: await readBankStatement(statementId, signal),
      runs: await listImportRuns(statementId, signal),
    }),
    [statementId],
  );

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

  const runs = phase.kind === "ready" ? phase.runs : [];
  // A run that has not finished is one the worker still holds. Starting a second is refused by the
  // server — two row sets for one file with nothing to say which is authoritative — so the button
  // says so before the click rather than after.
  const inFlight = runs.some((run) => run.status === "queued" || run.status === "running");

  return (
    <AdminShell>
      <section aria-labelledby="statement-heading" className="space-y-6">
        <Link className="text-sm underline" href="/bank-statements">
          {t("statement.backToList")}
        </Link>
        <h1 className="text-xl font-semibold" id="statement-heading">
          {t("statement.detailTitle")}
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
              <p aria-live="polite" className="rounded border p-3 text-sm" role="status">
                {notice}
              </p>
            ) : null}

            <dl className="space-y-1 rounded border p-4 text-sm" data-testid="statement-summary">
              <div>
                <dt className="inline font-medium">{t("statement.statusLabel")}: </dt>
                <dd className="inline">
                  <BidiText>{phase.statement.status}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="inline font-medium">{t("statement.rangeLabel")}: </dt>
                <dd className="inline">
                  <BidiText>
                    {phase.statement.date_range_start === null
                      ? t("statement.noRange")
                      : `${phase.statement.date_range_start} — ${phase.statement.date_range_end}`}
                  </BidiText>
                </dd>
              </div>
            </dl>

            <section aria-labelledby="runs-heading" className="space-y-3">
              <h2 className="text-lg font-semibold" id="runs-heading">
                {t("statement.runs")}
              </h2>

              {runs.length === 0 ? (
                <StateView
                  description={t("statement.noRuns")}
                  headingLevel={3}
                  kind="empty"
                  title={t("statement.noRunsTitle")}
                />
              ) : (
                <ul className="space-y-2" data-testid="import-run-list">
                  {runs.map((run) => (
                    <li className="rounded border p-3 text-sm" key={run.id}>
                      <span className="font-medium">
                        {t("statement.runNumber")}{" "}
                        <BidiText>{String(run.run_number)}</BidiText>
                      </span>
                      <span className="ms-3">
                        {t("statement.runStatus")}: <BidiText>{run.status}</BidiText>
                      </span>
                      <span className="ms-3">
                        {t("statement.rowCount")}:{" "}
                        {/* Null and zero say different things; rendering both as a number would
                            tell an operator the bank sent an empty file when nothing has run. */}
                        {run.row_count === null ? (
                          t("statement.rowCountPending")
                        ) : (
                          <BidiText>{String(run.row_count)}</BidiText>
                        )}
                      </span>
                      <span className="ms-3 text-[var(--ink-600)]">
                        {t("statement.parserVersion")}: <BidiText>{run.parser_version}</BidiText>
                      </span>
                      {run.error_summary === null ? null : (
                        <p className="mt-2 text-[var(--danger-600)]">
                          {t("statement.errorSummary")}:{" "}
                          <BidiText>{JSON.stringify(run.error_summary)}</BidiText>
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}

              <p className="text-sm text-[var(--ink-600)]">{t("statement.startRunHint")}</p>
              <button
                className="rounded border px-3 py-1 font-bold disabled:opacity-50"
                data-testid="start-import-run"
                disabled={busy || inFlight}
                onClick={() => {
                  setBusy(true);
                  setNotice(null);
                  void startImportRun(statementId)
                    .then(async () => {
                      setNotice(t("statement.runQueued"));
                      setPhase(await load());
                    })
                    .catch(async (caught: unknown) => {
                      const message = (caught as { body?: { error?: { message?: string } } }).body
                        ?.error?.message;
                      setNotice(message ?? t("statement.runFailed"));
                      try {
                        setPhase(await load());
                      } catch {
                        /* the notice carries it */
                      }
                    })
                    .finally(() => setBusy(false));
                }}
                type="button"
              >
                {runs.length === 0 ? t("statement.startRun") : t("statement.startRunAgain")}
              </button>
            </section>
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}
