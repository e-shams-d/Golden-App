"use client";

import { queueSortLabel, t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";

import type { QueueListing, QueueRow } from "../src/queues";

/**
 * The rows of any queue, and the controls §19.3 (`15_Agent_Implementation_Plan.md:1298`) requires.
 *
 * M11 Screens, slice 2. **One component for all sixteen**, which is not an economy but the payoff
 * of a backend decision: `QueueRow` is the same five fields for every queue, chosen so that §19
 * `:1298`'s last rule — a technical admin does not receive full financial detail by default — is
 * checkable once instead of sixteen times. Sixteen bespoke tables would each be a new opportunity
 * to add a column nobody authorised.
 *
 * **The filter and sort controls are rendered from the server's allowlist**, not from a list here.
 * Each queue publishes its own `filters` and `sorts`, and `read_queue_page` *refuses* an unlisted
 * key rather than ignoring it — so a hardcoded control would put a 400 in front of somebody doing
 * their job the day a spec changed. A queue that allows no filters simply gets no filter row.
 *
 * **No amount column, on any queue.** There is no amount in the contract to render; the note is
 * here because the absence is a disclosure decision rather than an omission, and a well-meaning
 * later change would add one to "the table" and inherit it sixteen times.
 */

export type QueueTableProps = Readonly<{
  listing: QueueListing;
  rows: readonly QueueRow[];
  total: number;
  sort: string;
  filters: Readonly<Record<string, string>>;
  busy: boolean;
  hasNextPage: boolean;
  atFirstPage: boolean;
  onSortChange: (sort: string) => void;
  onFilterChange: (key: string, value: string) => void;
  onApplyFilters: () => void;
  onClearFilters: () => void;
  onNextPage: () => void;
  onFirstPage: () => void;
}>;

/**
 * The label for a filter key. Only the two the sixteen queues actually allowlist have names; a
 * third would render its raw key, which reads badly and is honest — the same choice `queueLabel`
 * makes, and the reason `test_queue_screens_exist.py` checks the queue labels rather than trusting
 * that somebody remembered.
 */
function filterLabel(key: string): string {
  if (key === "trader_id") return t("queues.filterTrader");
  if (key === "task_type") return t("queues.filterTaskType");
  return key;
}

export function QueueTable({
  listing,
  rows,
  total,
  sort,
  filters,
  busy,
  hasNextPage,
  atFirstPage,
  onSortChange,
  onFilterChange,
  onApplyFilters,
  onClearFilters,
  onNextPage,
  onFirstPage,
}: QueueTableProps) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">{t("queues.sortLabel")}</span>
          <select
            className="rounded border px-2 py-1"
            disabled={busy}
            onChange={(event) => onSortChange(event.target.value)}
            value={sort}
          >
            {listing.sorts.map((field) => (
              <option key={field} value={field}>
                {queueSortLabel(field)}
              </option>
            ))}
          </select>
        </label>

        {listing.filters.map((key) => (
          <label className="flex flex-col gap-1 text-sm" key={key}>
            <span className="font-medium">{filterLabel(key)}</span>
            <input
              className="rounded border px-2 py-1"
              disabled={busy}
              onChange={(event) => onFilterChange(key, event.target.value)}
              type="text"
              value={filters[key] ?? ""}
            />
          </label>
        ))}

        {listing.filters.length > 0 ? (
          <div className="flex gap-2">
            <button
              className="rounded border px-3 py-1 text-sm"
              disabled={busy}
              onClick={onApplyFilters}
              type="button"
            >
              {t("queues.applyFilters")}
            </button>
            <button
              className="rounded border px-3 py-1 text-sm"
              disabled={busy}
              onClick={onClearFilters}
              type="button"
            >
              {t("queues.clearFilters")}
            </button>
          </div>
        ) : null}
      </div>

      {/* The server's count, announced rather than only drawn. It is deliberately not
          `rows.length`: a page is at most `limit` rows and the queue is however long it is, so
          the two differ by construction rather than in an edge case. */}
      <p aria-live="polite" className="text-sm">
        {t("queues.total").replace("{count}", String(total))}
      </p>

      {rows.length === 0 ? (
        <StateView
          description={t("queues.emptyDescription")}
          headingLevel={2}
          kind="empty"
          title={t("queues.emptyTitle")}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-start text-sm">
            <caption className="sr-only">
              {t("queues.showing").replace("{count}", String(rows.length))}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("queues.reference")}</th>
                <th scope="col">{t("queues.status")}</th>
                <th scope="col">{t("queues.createdAt")}</th>
                <th scope="col">{t("queues.trader")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                // `data-status` for the same reason the count is announced: a state that exists
                // only as a colour is a state some people cannot read.
                <tr data-status={row.status} key={row.id}>
                  <td>
                    <BidiText>{row.reference}</BidiText>
                  </td>
                  {/*
                    The raw status code, and this is a deliberate deferral rather than an
                    oversight. The sixteen queues draw from eight tables and their statuses are
                    eight separate vocabularies; document 06 defines seventeen for payment
                    requests alone and this release reaches six of them. A guessed Persian
                    translation of a financial state is a claim the software cannot support —
                    `paymentRequestStatusLabel` says so in its own note and returns the code for
                    exactly that reason. A code an operator can search for beats a word that might
                    be wrong.
                  */}
                  <td>
                    <BidiText>{row.status}</BidiText>
                  </td>
                  <td>
                    <BidiText>{row.created_at}</BidiText>
                  </td>
                  <td>
                    {row.trader_id === null ? (
                      // Not every queue is about one business: a batch version spans many and a
                      // maintenance task belongs to none. An em dash rather than a blank cell,
                      // which reads as a missing value.
                      <span>{t("queues.noTrader")}</span>
                    ) : (
                      <BidiText>{row.trader_id}</BidiText>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/*
        A cursor forward and a return to the start — deliberately not "previous".

        A cursor is one-directional: going back would need the cursor of the page before, which
        means keeping a stack and being wrong whenever rows shift under a person draining the
        queue. "Back to the start" is a claim this paging model can actually keep.
      */}
      <div className="flex gap-2">
        <button
          className="rounded border px-3 py-1 text-sm"
          disabled={busy || !hasNextPage}
          onClick={onNextPage}
          type="button"
        >
          {t("queues.nextPage")}
        </button>
        <button
          className="rounded border px-3 py-1 text-sm"
          disabled={busy || atFirstPage}
          onClick={onFirstPage}
          type="button"
        >
          {t("queues.previousPage")}
        </button>
      </div>
    </div>
  );
}
