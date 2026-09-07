"use client";

import { t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { TraderShell } from "../../../../components/trader-shell";
import { readRequest, type RequestDetail } from "../../../../src/payment-requests";
import {
  acknowledgeResult,
  disputeResult,
  readPublication,
  shareFilePath,
  type TraderPublication,
} from "../../../../src/publications";

/**
 * What happened to a payment, and the two things its trader may say about it.
 * §9.9, §9.10 (`15_Agent_Implementation_Plan.md:1273`), §9.11 (`:1277`).
 *
 * M11 Screens, slice 3. M9 published results and built the share file; no trader has seen any of
 * it. A **failed** payment does not arrive here at all — M9 decided it reaches its trader as a
 * notification, which is why slice 1 built that screen first.
 *
 * **The buttons come from `allowed_actions`, and until this slice there were none to come.**
 * `allowed_actions` projects the commands' own guards so a screen shows what the server said
 * rather than guessing; it did not project acknowledge or dispute, so this screen would have had
 * to derive them from `status`, `acknowledged_at` and `disputed_at`. That is the second list
 * beside the guards the projection exists to prevent, and it fails in the direction that matters:
 * offering a button the server refuses. Slice 3 added the projection rather than the derivation.
 *
 * **`If-Match` is the request's `ETag`, echoed.** Not the publication's, and not computed from
 * `record_version`: the version that can go stale is the request row a correction touches, so the
 * precondition is whatever the request read returned.
 *
 * **A dispute reverses nothing**, and the screen says so before the button rather than after. Doc
 * 05: "A dispute creates a visible manual review task and does not automatically reverse bank
 * facts." A control that reads like an undo is worse than no control.
 *
 * **No version history, because the trader has no route to one.** §20.3 gives the trader their
 * active publication only. `publication_version` above 1 is what tells them a correction happened,
 * and that is stated plainly instead of a list this app cannot fetch.
 */

const ACKNOWLEDGE = "payment_publication.acknowledge_own";
const DISPUTE = "payment_publication.dispute_own";

/**
 * The reason codes this screen offers, and **deliberately only two.**
 *
 * The first draft of this list had four invented codes — `amount_mismatch`, `not_received`,
 * `wrong_beneficiary`, `other` — and it contradicted a decision the backend had already made and
 * written down. `app/commands/trader_result.py`: *"`reason_code` is required and not enumerated.
 * Doc 05 shows one value, `beneficiary_did_not_receive`, and no catalogue names a set. A closed
 * list invented here would refuse a trader whose complaint does not fit one of the options
 * somebody guessed — and this is the only surface in the system whose user is a customer rather
 * than staff, so the cost of that is a phone call instead of a record."*
 *
 * A dropdown is exactly how that harm arrives: the server accepts anything, and the screen becomes
 * the closed list M9 refused to write. So the options are the one value doc 05 documents and a
 * general one, the general one is the default, and **the description is where the complaint
 * actually lives** — required, free text, in the person's own words.
 *
 * The list M0 owes is already recorded against M9. When it exists this becomes it.
 */
const REASONS = [
  { code: "other", label: "other" },
  { code: "beneficiary_did_not_receive", label: "notReceived" },
] as const;

type Phase =
  | { readonly kind: "loading" }
  | {
      readonly kind: "ready";
      readonly publication: TraderPublication;
      readonly detail: RequestDetail;
      readonly ifMatch: string;
    }
  | { readonly kind: "absent" }
  | { readonly kind: "failed" };

export default function TraderResultPage() {
  const parameters = useParams<{ requestId: string }>();
  const requestId = typeof parameters.requestId === "string" ? parameters.requestId : "";

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [showDispute, setShowDispute] = useState(false);
  const [reasonCode, setReasonCode] = useState<string>(REASONS[0].code);
  const [description, setDescription] = useState("");
  const [refused, setRefused] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal): Promise<Phase> => {
      // The request read first, because it carries the `ETag` every command here needs and the
      // `allowed_actions` that decide which buttons exist. Without it a publication could be
      // rendered with no honest way to act on it.
      const { detail, ifMatch } = await readRequest(requestId, signal);
      try {
        const publication = await readPublication(requestId, signal);
        return { kind: "ready", publication, detail, ifMatch };
      } catch {
        // A request with no published result answers 404, and so does another trader's request.
        // Both are "there is nothing here for you", which is the only thing this screen can
        // honestly say — distinguishing them would confirm somebody else's request exists.
        return { kind: "absent" };
      }
    },
    [requestId],
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

  /**
   * After either command, re-read rather than patching the row in place.
   *
   * The optimistic version is shorter and wrong under failure: if the command is refused the
   * screen has already told the person their dispute was filed. One extra round trip cannot lie —
   * and it is also what brings back a fresh `ETag`, which the next command needs.
   */
  const refresh = async () => {
    try {
      setPhase(await load());
    } catch {
      setPhase({ kind: "failed" });
    }
  };

  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    setRefused(null);
    try {
      await run();
      setShowDispute(false);
      setDescription("");
      await refresh();
    } catch (error) {
      // **412 gets its own message, because on this screen it means something specific.** A stale
      // precondition here is not "somebody edited a form under you" — it is that the centre
      // corrected the result while this person was reading it, which is the exact event the
      // request's version exists to catch. Telling them "the result changed, here is the new one"
      // is the difference between a refusal they understand and one that looks like a fault.
      const status = (error as { status?: number }).status;
      setRefused(status === 412 ? t("result.stale") : t("result.refused"));
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const actions = phase.kind === "ready" ? phase.detail.allowed_actions : [];
  const mayAcknowledge = actions.includes(ACKNOWLEDGE);
  const mayDispute = actions.includes(DISPUTE);

  return (
    <TraderShell>
      <section aria-labelledby="result-heading" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-xl font-semibold" id="result-heading">
            {t("result.title")}
          </h1>
          <Link className="rounded border px-3 py-1 text-sm" href={`/requests/${requestId}`}>
            {t("result.backToRequest")}
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

        {phase.kind === "absent" ? (
          <StateView
            description={t("result.absentDescription")}
            headingLevel={2}
            kind="empty"
            title={t("result.absentTitle")}
          />
        ) : null}

        {phase.kind === "failed" ? (
          <StateView
            description={t("result.failed")}
            headingLevel={2}
            kind="error"
            title={t("result.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            <dl className="grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-sm font-medium">{t("result.publishedAt")}</dt>
                <dd>
                  <BidiText>{phase.publication.published_at}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("result.version")}</dt>
                <dd>{phase.publication.publication_version}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("result.requestStatus")}</dt>
                <dd>
                  <BidiText>{phase.publication.request_status}</BidiText>
                </dd>
              </div>
              <div>
                {/* The content hash, shown rather than hidden. It is what makes a downloaded card
                    checkable against what the platform says it published — the one field on this
                    screen a person can take somewhere else and verify. */}
                <dt className="text-sm font-medium">{t("result.contentHash")}</dt>
                <dd className="break-all text-xs">
                  <BidiText>{phase.publication.content_hash}</BidiText>
                </dd>
              </div>
            </dl>

            {/*
              A version above 1 means the centre corrected a result this trader may already have
              seen. Said in words because there is no history route to show instead: §20.3 gives
              the trader their active publication only.
            */}
            {phase.publication.publication_version > 1 ? (
              <p className="rounded border p-3 text-sm">{t("result.corrected")}</p>
            ) : null}

            {phase.publication.acknowledged_at !== null ? (
              <p aria-live="polite" className="rounded border p-3 text-sm">
                {t("result.acknowledgedAlready")}{" "}
                <BidiText>{phase.publication.acknowledged_at}</BidiText>
              </p>
            ) : null}
            {phase.publication.disputed_at !== null ? (
              <p aria-live="polite" className="rounded border p-3 text-sm">
                {t("result.disputedAlready")}{" "}
                <BidiText>{phase.publication.disputed_at}</BidiText>
              </p>
            ) : null}

            <p>
              {/* A link, not a fetch: the file is a stream and the browser saves one better than
                  this screen would. */}
              <a
                className="rounded border px-3 py-1 text-sm"
                href={shareFilePath(phase.publication.id)}
              >
                {t("result.downloadCard")}
              </a>
            </p>

            {refused !== null ? (
              <p aria-live="assertive" className="rounded border p-3 text-sm">
                {refused}
              </p>
            ) : null}

            {/*
              Absent, not disabled. A disabled button says "you could do this, but not now", which
              is false: there is nothing a trader can do to make an already-answered result
              answerable again. `UI-PUB-001` asks for exactly this distinction.
            */}
            {mayAcknowledge || mayDispute ? (
              <div className="flex flex-wrap gap-2">
                {mayAcknowledge ? (
                  <button
                    className="rounded border px-3 py-1"
                    disabled={busy}
                    onClick={() => act(() => acknowledgeResult(requestId, phase.ifMatch))}
                    type="button"
                  >
                    {t("result.acknowledge")}
                  </button>
                ) : null}
                {mayDispute ? (
                  <button
                    className="rounded border px-3 py-1"
                    disabled={busy}
                    onClick={() => setShowDispute(true)}
                    type="button"
                  >
                    {t("result.dispute")}
                  </button>
                ) : null}
              </div>
            ) : null}

            {showDispute ? (
              <form
                className="space-y-3 rounded border p-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void act(() =>
                    disputeResult(
                      requestId,
                      { reason_code: reasonCode, description },
                      phase.ifMatch,
                    ),
                  );
                }}
              >
                {/* Before the fields, not after the button. What a dispute does — and does not
                    do — is the thing a person needs to know before writing one. */}
                <p className="text-sm">{t("result.disputeReversesNothing")}</p>

                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("result.disputeReason")}</span>
                  <select
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setReasonCode(event.target.value)}
                    value={reasonCode}
                  >
                    {REASONS.map((reason) => (
                      <option key={reason.code} value={reason.code}>
                        {t(`result.reason.${reason.label}`)}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("result.disputeDescription")}</span>
                  {/* The hint says the list does not bind them, because with only a general
                      option and one specific one a person could reasonably assume it does. */}
                  <span className="text-xs opacity-80" id="dispute-description-hint">
                    {t("result.disputeDescriptionHint")}
                  </span>
                  <textarea
                    aria-describedby="dispute-description-hint"
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setDescription(event.target.value)}
                    required
                    rows={4}
                    value={description}
                  />
                </label>

                <div className="flex gap-2">
                  <button className="rounded border px-3 py-1" disabled={busy} type="submit">
                    {t("result.submitDispute")}
                  </button>
                  <button
                    className="rounded border px-3 py-1"
                    disabled={busy}
                    onClick={() => setShowDispute(false)}
                    type="button"
                  >
                    {t("result.cancelDispute")}
                  </button>
                </div>
              </form>
            ) : null}
          </>
        ) : null}
      </section>
    </TraderShell>
  );
}
