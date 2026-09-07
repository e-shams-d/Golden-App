"use client";

import { queueLabel, t } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../components/admin-shell";
import { QueueTable } from "../../../components/queue-table";
import { listQueues, readQueue, type QueueListing, type QueueRow } from "../../../src/queues";

/**
 * One of §19.2's queues, whichever one the path names. §10.3, §19.3 (`:1298`).
 *
 * M11 Screens, slice 2. **One route serves all sixteen** because every queue returns the same five
 * fields — the backend chose that shape so §19 `:1298`'s disclosure rule could be checked once,
 * and a single dynamic screen is what that decision buys.
 *
 * **The queue's own definition is fetched, not assumed.** The index says which filters and sorts
 * this queue accepts, and the controls are rendered from that answer. The alternative — a table of
 * sixteen queues and their allowlists in this file — is a copy of the registry that nobody keeps in
 * step, and its failure mode is a control that earns a 400 in front of somebody working.
 *
 * **A queue missing from the index renders "not yours" rather than an error.** §20.1 `:2114`:
 * frontend visibility is not authorization. Typing the URL of a queue you cannot read reaches a
 * route that answers 403 — the refusal is the server's — and this screen chooses to say so plainly
 * instead of showing a failure that looks like a bug.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "unknown" }
  | {
      readonly kind: "ready";
      readonly listing: QueueListing;
      readonly rows: readonly QueueRow[];
      readonly total: number;
      readonly nextCursor: string | null;
    }
  | { readonly kind: "failed" };

export default function AdminQueuePage() {
  const parameters = useParams<{ queue: string }>();
  const name = typeof parameters.queue === "string" ? parameters.queue : "";

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [sort, setSort] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  // The values a person has typed but not yet applied. Separate from `applied` so that typing
  // does not fire a request per keystroke, and so "clear" is one request rather than one per field.
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [applied, setApplied] = useState<Record<string, string>>({});

  const load = useCallback(
    async (
      currentSort: string,
      currentCursor: string | null,
      currentFilters: Record<string, string>,
      signal?: AbortSignal,
    ): Promise<Phase> => {
      const index = await listQueues(signal);
      const listing = index.items.find((item) => item.name === name);
      // Absent from the index means the session's grants do not include this queue — or that no
      // such queue exists. The screen cannot tell those apart and deliberately does not try:
      // saying "no such queue for you" is true of both, where "you are not allowed" would be a
      // guess and would also confirm the queue exists.
      if (!listing) return { kind: "unknown" };

      const page = await readQueue(
        name,
        {
          filters: currentFilters,
          ...(currentSort ? { sort: currentSort } : {}),
          cursor: currentCursor,
          limit: 25,
        },
        signal,
      );
      return {
        kind: "ready",
        listing,
        rows: page.items,
        total: page.total,
        nextCursor: page.next_cursor,
      };
    },
    [name],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(sort, cursor, applied, controller.signal)
      .then((next) => setPhase(next))
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, [load, sort, cursor, applied]);

  /**
   * Any control that changes what is being asked returns to the first page.
   *
   * A cursor is only meaningful for the query it came from: keeping it across a sort change would
   * resume from a position in a different ordering, which is how paging quietly skips rows.
   */
  const changeSort = (next: string) => {
    setBusy(true);
    setCursor(null);
    setSort(next);
    setBusy(false);
  };

  const apply = () => {
    setCursor(null);
    setApplied({ ...draft });
  };

  const clear = () => {
    setCursor(null);
    setDraft({});
    setApplied({});
  };

  return (
    <AdminShell>
      <section aria-labelledby="queue-heading" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-xl font-semibold" id="queue-heading">
            {queueLabel(name)}
          </h1>
          <Link className="rounded border px-3 py-1 text-sm" href="/">
            {t("queues.backToIndex")}
          </Link>
        </div>

        {phase.kind === "loading" ? (
          <StateView
            description={t("state.loading.description")}
            headingLevel={2}
            kind="loading"
            title={t("state.loading.title")}
          />
        ) : null}

        {phase.kind === "unknown" ? (
          <StateView
            description={t("queues.unknownDescription")}
            headingLevel={2}
            kind="empty"
            title={t("queues.unknownTitle")}
          />
        ) : null}

        {phase.kind === "failed" ? (
          <StateView
            description={t("queues.failed")}
            headingLevel={2}
            kind="error"
            title={t("queues.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <QueueTable
            atFirstPage={cursor === null}
            busy={busy}
            filters={draft}
            hasNextPage={phase.nextCursor !== null}
            listing={phase.listing}
            onApplyFilters={apply}
            onClearFilters={clear}
            onFilterChange={(key, value) => setDraft((current) => ({ ...current, [key]: value }))}
            onFirstPage={() => setCursor(null)}
            onNextPage={() => setCursor(phase.nextCursor)}
            onSortChange={changeSort}
            rows={phase.rows}
            sort={sort || phase.listing.default_sort}
            total={phase.total}
          />
        ) : null}
      </section>
    </AdminShell>
  );
}
