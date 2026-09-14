"use client";

import { t, toPersianDigits } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import { useCallback, useEffect, useState } from "react";

import {
  acceptCandidate,
  listCandidates,
  type MatchingCandidate,
  proposeCandidate,
  rejectCandidate,
  type SegmentSummary,
} from "../src/bundles";
import { type AttemptSummary, searchAttempts } from "../src/payment-results";

/**
 * §16.3's candidate drawer: which payment this cut of a bank result is evidence for.
 *
 * M0 slice E. M9 slice 1 built the four routes and recorded the drawer as owed; this is the drawer.
 *
 * **Accepting a candidate marks nothing paid, and this component says so twice** — once beside the
 * button and once in the confirmation. `05_API_Specification.md:1810` states the prohibition,
 * `:1274` repeats it and `command_catalog.yaml:296` carries it as a precondition. A drawer whose
 * accept button read like a payment confirmation would be the one place a person could believe
 * money had moved because a screen implied it.
 *
 * **The search is seeded from the segment, not from an empty box.** The segment carries what the
 * platform read off the receipt — an amount and a tracking number — and those are the two fields
 * matching is built on. An operator who had to retype an amount they were looking at would mistype
 * it, and the wrong attempt would be a plausible one.
 *
 * **A null extracted field is not a missing receipt.** §8.4 requires an unparseable value to be
 * left null rather than guessed, so the search falls back to being typed by hand and says why.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly candidates: readonly MatchingCandidate[] }
  | { readonly kind: "failed" };

/** The statuses a decision is still open on, as `matching_candidate` spells them. */
const OPEN = "proposed";

export function SegmentCandidates({ segment }: { segment: SegmentSummary }) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [matches, setMatches] = useState<readonly AttemptSummary[] | null>(null);
  const [amount, setAmount] = useState(segment.extracted_amount_irr ?? "");
  const [tracking, setTracking] = useState(segment.extracted_tracking_number ?? "");
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal): Promise<Phase> => ({
      kind: "ready",
      candidates: await listCandidates(segment.id, signal),
    }),
    [segment.id],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((next) => setPhase(next))
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, [load]);

  const act = (run: () => Promise<unknown>) => {
    setBusy(true);
    setNotice(null);
    void run()
      .then(async () => setPhase(await load()))
      .catch(async (caught: unknown) => {
        const message = (caught as { body?: { error?: { message?: string } } }).body?.error
          ?.message;
        setNotice(message ?? t("candidate.failed"));
        try {
          setPhase(await load());
        } catch {
          /* the notice carries it */
        }
      })
      .finally(() => setBusy(false));
  };

  const search = () => {
    setBusy(true);
    setNotice(null);
    // The amount is a string all the way to the query because an IRR figure can exceed
    // `Number.MAX_SAFE_INTEGER` — `MONEY_TIME_CONTRACT.md` rule 9. It becomes a number only here,
    // where the contract's query parameter is an integer, and a value that cannot survive the trip
    // is refused rather than rounded.
    const digits = amount.trim();
    if (digits !== "" && !Number.isSafeInteger(Number(digits))) {
      setNotice(t("candidate.amountTooLarge"));
      setBusy(false);
      return;
    }
    void searchAttempts({
      ...(digits === "" ? {} : { amountIrr: Number(digits) }),
      ...(tracking.trim() === "" ? {} : { bankTrackingNumber: tracking.trim() }),
      limit: 20,
    })
      .then((found) => setMatches(found))
      .catch(() => setNotice(t("candidate.searchFailed")))
      .finally(() => setBusy(false));
  };

  return (
    <section aria-labelledby={`candidates-${segment.id}`} className="space-y-4">
      <h3 className="text-lg font-bold" id={`candidates-${segment.id}`}>
        {t("candidate.title")}
      </h3>
      {/* Said before anything is clicked, not in the confirmation alone. */}
      <p className="text-sm text-[var(--muted)]">{t("candidate.advisory")}</p>

      {notice !== null ? (
        <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
          {notice}
        </p>
      ) : null}

      {phase.kind === "loading" ? (
        <StateView
          description={t("state.loading.description")}
          headingLevel={3}
          kind="loading"
          title={t("state.loading.title")}
        />
      ) : null}

      {phase.kind === "failed" ? (
        <StateView
          description={t("candidate.failed")}
          headingLevel={3}
          kind="error"
          title={t("candidate.failedTitle")}
        />
      ) : null}

      {phase.kind === "ready" ? (
        <>
          {phase.candidates.length === 0 ? (
            <StateView
              description={t("candidate.noneDescription")}
              headingLevel={3}
              kind="empty"
              title={t("candidate.noneTitle")}
            />
          ) : (
            <ul className="space-y-2" data-testid="candidate-list">
              {phase.candidates.map((candidate) => (
                <li className="rounded border p-3 text-sm" key={candidate.id}>
                  <p>
                    <span className="font-medium">{t("candidate.attempt")}: </span>
                    <BidiText>{candidate.payment_attempt_id}</BidiText>
                  </p>
                  <p>
                    <span className="font-medium">{t("candidate.status")}: </span>
                    <BidiText>{candidate.status}</BidiText>
                    <span className="ms-3 text-[var(--muted)]">
                      {t("candidate.method")}: <BidiText>{candidate.method}</BidiText>
                    </span>
                    {/* Null and a number say different things: no score means nobody computed
                        one, which is what a manual proposal always looks like. */}
                    <span className="ms-3 text-[var(--muted)]">
                      {t("candidate.score")}:{" "}
                      {candidate.score === null ? (
                        t("candidate.noScore")
                      ) : (
                        <BidiText>{candidate.score}</BidiText>
                      )}
                    </span>
                  </p>

                  {candidate.status === OPEN ? (
                    <div className="mt-2 space-y-2">
                      <button
                        className="rounded border px-3 py-1 font-bold disabled:opacity-50"
                        data-testid="candidate-accept"
                        disabled={busy}
                        onClick={() => act(() => acceptCandidate(candidate.id))}
                        type="button"
                      >
                        {t("candidate.accept")}
                      </button>
                      <p className="text-xs text-[var(--muted)]">{t("candidate.acceptNotPaid")}</p>

                      <label className="block">
                        <span className="font-medium">{t("candidate.rejectReason")}</span>
                        <input
                          className="mt-1 w-full rounded border p-2"
                          data-testid="candidate-reason"
                          disabled={busy}
                          onChange={(event) =>
                            setReasons({ ...reasons, [candidate.id]: event.target.value })
                          }
                          value={reasons[candidate.id] ?? ""}
                        />
                      </label>
                      <button
                        className="rounded border px-3 py-1 disabled:opacity-50"
                        data-testid="candidate-reject"
                        // The server requires a reason for every rejection, so the button waits
                        // for one rather than sending a request that will be refused.
                        disabled={busy || (reasons[candidate.id] ?? "").trim() === ""}
                        onClick={() =>
                          act(() => rejectCandidate(candidate.id, reasons[candidate.id] ?? ""))
                        }
                        type="button"
                      >
                        {t("candidate.reject")}
                      </button>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}

          <section aria-labelledby={`propose-${segment.id}`} className="space-y-3 rounded border p-3">
            <h4 className="font-bold" id={`propose-${segment.id}`}>
              {t("candidate.propose")}
            </h4>
            {segment.extracted_amount_irr === null &&
            segment.extracted_tracking_number === null ? (
              // Neither field was readable. §8.4 leaves it null rather than guessing, and saying so
              // is the difference between "we read nothing" and "the receipt was blank".
              <p className="text-sm text-[var(--muted)]">{t("candidate.nothingExtracted")}</p>
            ) : null}

            <label className="block text-sm">
              <span className="font-medium">{t("candidate.amount")}</span>
              <input
                className="mt-1 w-full rounded border p-2"
                data-testid="candidate-amount"
                disabled={busy}
                inputMode="numeric"
                onChange={(event) => setAmount(event.target.value)}
                value={amount}
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium">{t("candidate.tracking")}</span>
              <input
                className="mt-1 w-full rounded border p-2"
                data-testid="candidate-tracking"
                disabled={busy}
                onChange={(event) => setTracking(event.target.value)}
                value={tracking}
              />
            </label>
            <button
              className="rounded border px-3 py-1 font-bold disabled:opacity-50"
              data-testid="candidate-search"
              disabled={busy || (amount.trim() === "" && tracking.trim() === "")}
              onClick={search}
              type="button"
            >
              {t("candidate.search")}
            </button>

            {matches === null ? null : matches.length === 0 ? (
              <p className="text-sm" data-testid="candidate-no-matches">
                {t("candidate.noMatches")}
              </p>
            ) : (
              <ul className="space-y-2" data-testid="attempt-matches">
                {matches.map((attempt) => (
                  <li className="rounded border p-2 text-sm" key={attempt.id}>
                    <span className="font-medium">
                      {t("candidate.attemptNumber")}{" "}
                      <BidiText>{toPersianDigits(String(attempt.attempt_number))}</BidiText>
                    </span>
                    <span className="ms-3">
                      {/* Rendered as a string. `MONEY_TIME_CONTRACT.md` rule 9 forbids arithmetic
                          on an IRR figure in JavaScript, and nothing here does any. */}
                      <BidiText>{toPersianDigits(String(attempt.amount_irr))}</BidiText>
                    </span>
                    <span className="ms-3 text-[var(--muted)]">
                      <BidiText>{attempt.status}</BidiText>
                    </span>
                    <button
                      className="ms-3 rounded border px-2 py-1 disabled:opacity-50"
                      data-testid="candidate-propose"
                      disabled={busy}
                      onClick={() => act(() => proposeCandidate(segment.id, attempt.id))}
                      type="button"
                    >
                      {t("candidate.proposeThis")}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </section>
  );
}
