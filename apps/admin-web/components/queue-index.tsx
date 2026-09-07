"use client";

import { queueLabel, t } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";
import { useEffect, useState } from "react";

import { listQueues, type QueueListing } from "../src/queues";

/**
 * The per-role landing surface §10.3 asks for: every queue that is this person's, with how much is
 * waiting in it.
 *
 * M11 Screens, slice 2. Until now this section of the dashboard rendered **four invented queue
 * names and an em dash**, with a screen-reader note saying «تعداد هنوز دریافت نشده است». That was
 * honest for eleven milestones and is now simply false — the routes exist, the counts are the
 * server's, and none of the four names was one §19.2 gives.
 *
 * **The list is the server's answer, not a filter applied here.** `GET /api/v1/queues` returns only
 * the queues whose own grant the session holds. §20.1 `:2114` — frontend visibility is not
 * authorization — so this is not the control; the control is that each queue's route refuses a
 * caller without its grant, which `tests/integration/test_queue_index.py` asserts.
 *
 * **An empty list is a sentence, not a blank panel.** A person holding no queue grant sees "none of
 * these are yours", which is true. The alternative — an empty grid — is indistinguishable from a
 * failed load, and this project has been bitten by that shape before.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly items: readonly QueueListing[]; readonly total: number }
  | { readonly kind: "failed" };

export function QueueIndexPanel() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });

  // Set from the promise callback rather than after an await in the effect body:
  // `react-hooks/set-state-in-effect` refuses the second shape, and the abort is the other half —
  // leaving the page mid-request must not set state on a component that is gone.
  useEffect(() => {
    const controller = new AbortController();
    listQueues(controller.signal)
      .then((index) => setPhase({ kind: "ready", items: index.items, total: index.total }))
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, []);

  if (phase.kind === "loading") {
    return (
      <StateView
        description={t("state.loading.description")}
        headingLevel={3}
        kind="loading"
        title={t("state.loading.title")}
      />
    );
  }

  if (phase.kind === "failed") {
    return (
      <StateView
        description={t("admin.queueFailed")}
        headingLevel={3}
        kind="error"
        title={t("admin.queueFailedTitle")}
      />
    );
  }

  if (phase.items.length === 0) {
    return (
      <StateView
        description={t("admin.queueEmptyDescription")}
        headingLevel={3}
        kind="empty"
        title={t("admin.queueEmptyTitle")}
      />
    );
  }

  return (
    <>
      {/* Announced, not only drawn. The sum across a person's own queues is the number they act
          on — "is there anything for me today" — and it is deliberately not a system-wide total:
          two roles asking get different answers because they have different work. */}
      <p aria-live="polite" className="text-sm">
        {t("queues.total").replace("{count}", String(phase.total))}
      </p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {phase.items.map((listing) => (
          <article
            className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"
            key={listing.name}
          >
            <h3 className="font-black">{queueLabel(listing.name)}</h3>
            <p className="mt-4 text-3xl font-black">{listing.waiting}</p>
            {/* The count is repeated in words for a screen reader, because a bare numeral in a
                card says nothing about what it counts. */}
            <p className="sr-only">
              {t("admin.queueWaiting").replace("{count}", String(listing.waiting))}
            </p>
            <Link
              className="mt-4 inline-block rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-bold"
              href={`/queues/${listing.name}`}
            >
              {t("admin.queueOpen")}
            </Link>
          </article>
        ))}
      </div>
    </>
  );
}
