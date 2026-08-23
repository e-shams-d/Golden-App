"use client";

import { t, toPersianDigits } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../components/admin-shell";
import { listBatches, type QueueRow } from "../../src/batches";

/**
 * The manager's approval queue. §13.2 of the screen specification.
 *
 * **Every row identifies the exact version**, which is that section's opening sentence and the
 * reason this screen exists in the shape it does: a batch may have had several versions, a
 * manager approves one of them, and a queue keyed on the batch alone would ask somebody to
 * decide about the wrong thing. `version_number` is beside the batch reference in every row and
 * the link carries the version id.
 *
 * **Ten columns, and none of them computed here.** `warning_count` arrives counted,
 * `prepared_by` and `finalized_by` arrive as names, and the bank and source account arrive
 * resolved. Slice 0 added all of that to the read for this screen; deriving any of it client-side
 * would be a second answer to a question the server already answered.
 *
 * **The default view is what is waiting.** `awaiting_decision=true` is the queue; the toggle
 * shows everything, because §13.4 requires a superseded version's page to stay reachable and a
 * filter that became the only view would take that away.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly rows: readonly QueueRow[] }
  | { readonly kind: "forbidden" }
  | { readonly kind: "failed" };

export default function AdminBatchesPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [awaiting, setAwaiting] = useState(true);

  // A 403 is a different screen from a 500: one says "not for you", the other says "try again".
  const phaseForError = (error: unknown): Phase =>
    (error as { status?: number }).status === 403 ? { kind: "forbidden" } : { kind: "failed" };

  const load = useCallback(
    (next: boolean, signal?: AbortSignal) =>
      listBatches(next, signal)
        .then((rows) => setPhase({ kind: "ready", rows }))
        .catch((error: unknown) => {
          if (!signal?.aborted) setPhase(phaseForError(error));
        }),
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(awaiting, controller.signal);
    return () => controller.abort();
  }, [load, awaiting]);

  const choose = (value: boolean) => {
    if (value === awaiting) return;
    setPhase({ kind: "loading" });
    setAwaiting(value);
  };

  return (
    <AdminShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("admin.batches.title")}</h1>
        <p className="mt-3 max-w-3xl leading-8 text-[var(--ink-600)]">
          {t("admin.batches.description")}
        </p>

        <div className="mt-5 flex flex-wrap gap-2">
          {[true, false].map((value) => (
            <button
              aria-pressed={awaiting === value}
              className={`rounded-full border px-4 py-2 font-bold ${
                awaiting === value
                  ? "border-[var(--gold-700)] bg-[var(--gold-700)] text-white"
                  : "border-[var(--border)]"
              }`}
              key={String(value)}
              onClick={() => choose(value)}
              type="button"
            >
              {value ? t("admin.batches.filterAwaiting") : t("admin.batches.filterAll")}
            </button>
          ))}
        </div>

        <div className="mt-6">
          {phase.kind === "loading" ? (
            <StateView
              description={t("admin.batches.loading")}
              headingLevel={2}
              kind="loading"
              title={t("admin.batches.loading")}
            />
          ) : null}

          {phase.kind === "forbidden" ? (
            <StateView
              description={t("admin.batches.forbidden")}
              headingLevel={2}
              kind="forbidden"
              title={t("admin.batches.forbiddenTitle")}
            />
          ) : null}

          {phase.kind === "failed" ? (
            <StateView
              actions={
                <button
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-2 font-bold"
                  onClick={() => void load(awaiting)}
                  type="button"
                >
                  {t("common.refresh")}
                </button>
              }
              description={t("admin.batches.failed")}
              headingLevel={2}
              kind="error"
              title={t("admin.batches.failedTitle")}
            />
          ) : null}

          {phase.kind === "ready" && phase.rows.length === 0 ? (
            <StateView
              description={t("admin.batches.empty")}
              headingLevel={2}
              kind="empty"
              title={t("admin.batches.emptyTitle")}
            />
          ) : null}

          {phase.kind === "ready" && phase.rows.length > 0 ? (
            <ul className="mt-2 grid gap-3">
              {phase.rows.map((row) => (
                <li
                  className="rounded-2xl border border-[var(--border)] bg-[var(--surface-subtle)] p-4"
                  key={row.version_id ?? row.id}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-3">
                    <h2 className="text-xl font-black">
                      {row.batch_number}
                      {/* §13.2's first sentence. The version is never implied by the batch. */}
                      <span className="mx-2 text-[var(--ink-600)]">·</span>
                      <span data-testid="version-number">
                        {t("admin.batches.versionLabel")}{" "}
                        {row.version_number === null
                          ? t("common.unknown")
                          : toPersianDigits(String(row.version_number))}
                      </span>
                    </h2>
                    {row.version_id ? (
                      <Link
                        className="rounded-lg border border-[var(--gold-700)] px-3 py-1 font-bold text-[var(--gold-700)]"
                        href={`/batches/${row.id}/versions/${row.version_id}`}
                      >
                        {t("admin.batches.open")}
                      </Link>
                    ) : null}
                  </div>

                  <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
                    <Cell label={t("admin.batches.total")}>
                      {toPersianDigits(row.total_amount_irr)}
                    </Cell>
                    <Cell label={t("admin.batches.rowCount")}>
                      {toPersianDigits(String(row.row_count))}
                    </Cell>
                    <Cell label={t("admin.batches.bank")}>{row.bank ?? t("common.unknown")}</Cell>
                    <Cell label={t("admin.batches.sourceAccount")}>
                      {row.source_account ?? t("common.unknown")}
                    </Cell>
                    <Cell label={t("admin.batches.mappingVersion")}>
                      {row.mapping_version === null
                        ? t("common.unknown")
                        : toPersianDigits(String(row.mapping_version))}
                    </Cell>
                    <Cell label={t("admin.batches.warningCount")}>
                      {toPersianDigits(String(row.warning_count))}
                    </Cell>
                    <Cell label={t("admin.batches.preparedBy")}>
                      {row.prepared_by ?? t("common.unknown")}
                    </Cell>
                    <Cell label={t("admin.batches.finalizedBy")}>
                      {/* Null is a real answer: a draft has no finalizer. */}
                      {row.finalized_by ?? t("admin.batches.notFinalized")}
                    </Cell>
                    <Cell label={t("admin.batches.age")}>
                      {row.version_created_at ?? t("common.unknown")}
                    </Cell>
                  </dl>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </section>
    </AdminShell>
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
