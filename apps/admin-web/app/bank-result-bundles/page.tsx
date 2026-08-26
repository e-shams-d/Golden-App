"use client";

import { t, toPersianDigits } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../components/admin-shell";
import { type BundleSummary, byOutstandingWork, listBundles } from "../../src/bundles";

/**
 * The bank-result queue. `05_API_Specification.md:1676`, and the workspace's way in.
 *
 * **Built because a gate refused the workspace without it.** `UI-REQ-004` found
 * `/bank-result-bundles/[bundleId]` reachable only by typing a URL, which is not a tidiness
 * complaint: nobody memorises a bundle id, so a workspace with no queue is a workspace nobody
 * opens.
 *
 * **Sorted by outstanding work, not by arrival.** §16.3's first item is "bundle summary and
 * unresolved navigation", and the question somebody opens this with is "what still needs me". Date
 * breaks the tie, oldest first, because a bundle that has waited longer is the one to look at.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly rows: readonly BundleSummary[] }
  | { readonly kind: "forbidden" }
  | { readonly kind: "failed" };

export default function BankResultBundlesPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });

  const load = useCallback(
    (signal?: AbortSignal) =>
      listBundles(signal)
        .then((rows) => setPhase({ kind: "ready", rows: byOutstandingWork(rows) }))
        .catch((error: unknown) => {
          if (signal?.aborted) return;
          setPhase(
            (error as { status?: number }).status === 403
              ? { kind: "forbidden" }
              : { kind: "failed" },
          );
        }),
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return (
    <AdminShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("admin.bundles.title")}</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">{t("admin.bundles.explanation")}</p>

        {phase.kind === "loading" ? (
          <StateView
            description={t("admin.bundles.loading")}
            headingLevel={2}
            kind="loading"
            title={t("admin.bundles.loading")}
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

        {phase.kind === "ready" && phase.rows.length === 0 ? (
          <StateView
            description={t("admin.bundles.emptyExplanation")}
            headingLevel={2}
            kind="empty"
            title={t("admin.bundles.empty")}
          />
        ) : null}

        {phase.kind === "ready" && phase.rows.length > 0 ? (
          <ul className="mt-6 flex flex-col gap-3">
            {phase.rows.map((row) => (
              <li key={row.id}>
                <Link
                  className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-sunken)] px-4 py-3 font-bold"
                  href={`/bank-result-bundles/${row.id}`}
                >
                  <span>{row.bundle_number}</span>
                  <span className="text-sm font-normal text-[var(--muted)]">
                    {t("admin.workspace.state")}: {row.status}
                  </span>
                  <span className="text-sm font-normal">
                    {t("admin.workspace.unresolved")}:{" "}
                    {toPersianDigits(String(row.unresolved_segment_count))}
                    {" / "}
                    {toPersianDigits(String(row.segment_count))}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </AdminShell>
  );
}
