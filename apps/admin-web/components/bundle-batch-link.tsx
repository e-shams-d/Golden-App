"use client";

import { t, toPersianDigits } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import { useEffect, useState } from "react";

import {
  type BatchChoice,
  batchNumberInFileName,
  type BundleDetail,
  linkBundleToBatch,
  listBatchesForLinking,
} from "../src/bundles";

/**
 * Which batch this bundle answers, chosen by a person.
 *
 * **The owner's decision of 2026-09-13.** Asked whether a human should ever link a result bundle to
 * a batch by hand, they answered by improving the question: give every batch a clear name, have the
 * accountant know which batch a returned file belongs to, and keep a manual correction possible.
 *
 * Batch numbers already existed — `PB-YYYYMMDD-NNNNNN`, unique and day-scoped — so this is the
 * choosing half.
 *
 * **The file name is a hint and never a decision, and that half is a deliberate departure from what
 * was asked.** The owner also suggested recognising the batch from the file's name, with an
 * instruction not to rename it. A name leaves this building: the bank renames it, a mail client
 * renames it, a download adds `(1)`, and the instruction is what gets skipped on a busy day. A
 * bundle attached to the *wrong* batch is invisible — every receipt in it would then be matched
 * against payments it has nothing to do with — while a bundle attached to nothing is a problem
 * somebody can see. So a name that looks like a batch number pre-selects that batch and says it is
 * a guess; the accountant confirms.
 *
 * **`proves_payment` is rendered, not assumed.** `05_API_Specification.md:1688` calls this
 * association "operational context only", and a batch number sitting beside a bundle reads as a
 * claim about payment unless something says otherwise. The server sends the field; this shows it.
 */

export function BundleBatchLink({
  bundle,
  onLinked,
}: {
  bundle: BundleDetail;
  onLinked: () => void;
}) {
  const [batches, setBatches] = useState<readonly BatchChoice[] | null>(null);
  const [chosen, setChosen] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    listBatchesForLinking(controller.signal)
      .then((found) => setBatches(found))
      .catch(() => {
        if (!controller.signal.aborted) setBatches([]);
      });
    return () => controller.abort();
  }, []);

  // The hint, computed from the files already on the bundle. Derived rather than stored, so it
  // cannot disagree with what the bundle actually holds.
  const suggestion =
    bundle.files.map((file) => batchNumberInFileName(file.file_name)).find((n) => n !== null) ??
    null;
  const suggested = batches?.find((batch) => batch.batch_number === suggestion) ?? null;

  const active = bundle.batch_links.filter((link) => link.replaced_at === null);

  return (
    <section aria-labelledby="bundle-batch-link" className="flex flex-col gap-3">
      <h2 className="text-xl font-bold" id="bundle-batch-link">
        {t("batchLink.title")}
      </h2>
      {/* §16.3's association is operational context. Said before a batch number is shown. */}
      <p className="text-sm text-[var(--muted)]">{t("batchLink.notProof")}</p>

      {notice !== null ? (
        <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
          {notice}
        </p>
      ) : null}

      {active.length === 0 ? (
        <StateView
          description={t("batchLink.noneDescription")}
          headingLevel={3}
          kind="empty"
          title={t("batchLink.noneTitle")}
        />
      ) : (
        <ul className="space-y-2" data-testid="batch-link-list">
          {active.map((link) => (
            <li className="rounded border p-3 text-sm" key={link.id}>
              <span className="font-medium">
                <BidiText>{link.batch_number}</BidiText>
              </span>
              <span className="ms-3 text-[var(--muted)]">
                {t("batchLink.method")}: <BidiText>{link.link_method}</BidiText>
              </span>
              <span className="ms-3 text-[var(--muted)]">
                {t("batchLink.by")}: <BidiText>{link.created_by ?? t("batchLink.bySystem")}</BidiText>
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Superseded links stay visible. `replaced_at` is set rather than the row deleted, so how a
          bundle came to be attached to a batch is answerable after somebody changed their mind. */}
      {bundle.batch_links.some((link) => link.replaced_at !== null) ? (
        <details className="text-sm">
          <summary className="cursor-pointer font-medium">{t("batchLink.previous")}</summary>
          <ul className="mt-2 space-y-1" data-testid="batch-link-history">
            {bundle.batch_links
              .filter((link) => link.replaced_at !== null)
              .map((link) => (
                <li className="text-[var(--muted)]" key={link.id}>
                  <BidiText>{link.batch_number}</BidiText>
                  <span className="ms-3">
                    <BidiText>{link.created_by ?? t("batchLink.bySystem")}</BidiText>
                  </span>
                </li>
              ))}
          </ul>
        </details>
      ) : null}

      {batches === null ? (
        <StateView
          description={t("state.loading.description")}
          headingLevel={3}
          kind="loading"
          title={t("state.loading.title")}
        />
      ) : batches.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">{t("batchLink.noBatches")}</p>
      ) : (
        <>
          {suggested === null ? null : (
            <p className="text-sm" data-testid="batch-link-suggestion">
              {t("batchLink.suggestion")} <BidiText>{suggested.batch_number}</BidiText>{" "}
              <span className="text-[var(--muted)]">{t("batchLink.suggestionIsAGuess")}</span>
            </p>
          )}

          <label className="block text-sm">
            <span className="font-medium">{t("batchLink.choose")}</span>
            <select
              className="mt-1 w-full rounded border p-2"
              data-testid="batch-link-choice"
              disabled={busy}
              onChange={(event) => setChosen(event.target.value)}
              // The suggestion pre-selects and the operator confirms. `value` falls back to it
              // rather than the effect writing state, so a reload cannot leave a stale choice.
              value={chosen || suggested?.id || ""}
            >
              <option value="">{t("batchLink.chooseNone")}</option>
              {batches.map((batch) => (
                <option key={batch.id} value={batch.id}>
                  {`${batch.batch_number} — ${batch.status} — ${toPersianDigits(
                    String(batch.row_count),
                  )}`}
                </option>
              ))}
            </select>
          </label>

          <button
            className="rounded border px-3 py-1 font-bold disabled:opacity-50"
            data-testid="batch-link-submit"
            disabled={busy || (chosen || suggested?.id || "") === ""}
            onClick={() => {
              const batchId = chosen || suggested?.id || "";
              if (batchId === "") return;
              setBusy(true);
              setNotice(null);
              // `manual_selection`, always. This surface is a person choosing, and recording it as
              // anything else would make a human decision indistinguishable from a guess later.
              void linkBundleToBatch(bundle.id, batchId, "manual_selection")
                .then(() => {
                  setNotice(t("batchLink.linked"));
                  onLinked();
                })
                .catch((caught: unknown) => {
                  const message = (caught as { body?: { error?: { message?: string } } }).body
                    ?.error?.message;
                  setNotice(message ?? t("batchLink.failed"));
                })
                .finally(() => setBusy(false));
            }}
            type="button"
          >
            {active.length === 0 ? t("batchLink.link") : t("batchLink.relink")}
          </button>
          {active.length === 0 ? null : (
            <p className="text-xs text-[var(--muted)]">{t("batchLink.relinkKeepsHistory")}</p>
          )}
        </>
      )}
    </section>
  );
}
