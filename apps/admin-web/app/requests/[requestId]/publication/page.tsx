"use client";

import { t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../../components/admin-shell";
import { CorrectionDialog } from "../../../../components/correction-dialog";
import { approverReauthenticate } from "../../../../src/auth";
import { readRequest } from "../../../../src/payment-requests";
import {
  correctPublication,
  listBundleSegments,
  listPublications,
  previewPublication,
  publishResult,
  readEvidenceLink,
  readReceiptSegment,
  type EvidenceLink,
  type Publication,
  type PublicationPreview,
  type ReceiptSegment,
} from "../../../../src/payment-results";

/**
 * `command_catalog.yaml`'s id for this command, and the resource it binds a step-up to.
 *
 * The purpose is the command id, exactly as the batch decisions use theirs: a context obtained to
 * correct a publication must not be spendable on anything else, and vice versa. The resource type
 * is the string `publication_correction.py` has carried in `STEP_UP_RESOURCE_TYPE` since M9 —
 * declared there, unread by anything, until this screen became its caller.
 */
const CORRECTION_PURPOSE = "payment_publication.correct";
const CORRECTION_RESOURCE_TYPE = "payment_result_publication";

/**
 * What the published evidence is, and what could replace it.
 *
 * `linkId` is carried on the value rather than kept in a second piece of state so that "is this
 * still about the publication on screen" is answerable without an effect that clears it. The
 * failed variant is a state rather than `null` for the same reason: a resolution that was
 * attempted and failed and one that has not been attempted yet say different things to a person,
 * and only the first should turn the button's explanation on.
 */
type Evidence =
  | Readonly<{ linkId: string; link: EvidenceLink; segments: readonly ReceiptSegment[] }>
  | Readonly<{ linkId: string; failed: true }>;

/**
 * What the trader will be told, before and after telling them.
 * §16.7 (`15_Agent_Implementation_Plan.md:1894`), §16.8 (`:1900`).
 *
 * M11 Screens, slice 4. M9 built the preview and the publish and nothing has ever called either
 * from a screen.
 *
 * **Preview first, and the screen enforces the order rather than suggesting it.** The publish
 * control appears only after a preview has been taken: §16.7 exists so a person sees the redacted
 * payload *before* it becomes immutable, and a publication cannot be unpublished — the correction
 * flow that would supersede it is blocked (below). One extra click against an irreversible act
 * that a trader then sees is the cheapest guard available.
 *
 * **`If-Match` is the request's version, not the publication's.** A publication has no prior
 * version to be stale against; the request does — an accountant who read it, went to make tea and
 * published while somebody else corrected the result would publish a snapshot of something that
 * had moved. Echoed from the request read's `ETag`, never built from `record_version`.
 *
 * **No step-up dialog, and that is a correction to this plan's own obligation.**
 * `UI-RESULT-001`'s first wording asked for the recent-auth dialog §8.11 specifies on the publish
 * button. §8.11 describes the dialog *component* — reauthentication is a separate step and must
 * not auto-submit the command — and says nothing about which commands need one.
 * `command_catalog.yaml` is the authority: `payment_publication.publish` carries **no**
 * `recent_auth` field, while `payment_publication.correct_paid_result` carries
 * `required_for_approving_second_human`. Asking a person to reauthenticate for a command that does
 * not require it trains them to type their password whenever a screen asks.
 *
 * **The correction control, which was a panel explaining its own absence for two milestones.**
 * That panel was right each time it was written and its reason expired twice. First: nobody held
 * `payment_publication.correct`, so a button would have answered 403 to everybody — the owner
 * assigned both halves on 2026-09-08. Then: the catalogue requires
 * `recent_auth: "required_for_approving_second_human"` and the mechanism could only prove the
 * *caller* was present — the owner decided on 2026-09-09 that the second human types their own
 * password, and `POST /auth/admin/approver-reauthenticate` is that decision.
 *
 * The third blocker was the quiet one and it was found while sizing the second. **A publication
 * cites `primary_evidence_link_id` and nothing could resolve it**: the evidence surface was three
 * POSTs, `GET /bank-result-bundles/{id}` returned three segment *counts*, and the queue whose name
 * says "segments" returns bundles. So the screen could not show which crop is published, could not
 * offer an alternative, and could not name a replacement. `getEvidenceLink` and
 * `listBundleReceiptSegments` are that chain, and they are M0 slice A2's, not this screen's alone —
 * the frontend plan's slices C and E need them too.
 */

type Phase =
  | { readonly kind: "loading" }
  | {
      readonly kind: "ready";
      readonly history: readonly Publication[];
      readonly ifMatch: string;
      readonly requestStatus: string;
    }
  | { readonly kind: "failed" };

export default function AdminPublicationPage() {
  const parameters = useParams<{ requestId: string }>();
  const requestId = typeof parameters.requestId === "string" ? parameters.requestId : "";

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<PublicationPreview | null>(null);
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const [evidence, setEvidence] = useState<Evidence | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal): Promise<Phase> => {
      // The request read supplies the `ETag` the publish command needs; the history is what has
      // already been said. Both, because the screen is about the difference between them.
      const { detail, ifMatch } = await readRequest(requestId, signal);
      const history = await listPublications(requestId, signal);
      return { kind: "ready", history, ifMatch, requestStatus: detail.request.status };
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

  const active =
    phase.kind === "ready"
      ? (phase.history.find((publication) => publication.status === "active") ?? null)
      : null;
  const activeLinkId = active?.primary_evidence_link_id ?? null;

  // **The correction's read chain, walked in the open.** publication -> link -> segment ->
  // bundle -> every segment of that bundle. Each hop is a route this contract publishes, and two
  // of them did not exist before M0 slice A2 — which is why this screen was deferred rather than
  // built badly.
  //
  // A failure is recorded as a state rather than rethrown, because the publication history is
  // still worth rendering when the evidence cannot be resolved: what a trader was told is the
  // more important half of this page, and losing it to a failed lookup of what could replace it
  // would be the wrong trade. The button explains itself instead.
  useEffect(() => {
    if (activeLinkId === null) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const link = await readEvidenceLink(activeLinkId, controller.signal);
        const segment = await readReceiptSegment(link.receipt_segment_id, controller.signal);
        const segments =
          segment.bank_result_bundle_id === null
            ? // Evidence attached from outside a bundle has no siblings to offer. The dialog
              // renders its own "nothing to choose" state rather than this reading as a failure.
              []
            : await listBundleSegments(segment.bank_result_bundle_id, controller.signal);
        if (!controller.signal.aborted) setEvidence({ linkId: activeLinkId, link, segments });
      } catch {
        if (!controller.signal.aborted) setEvidence({ linkId: activeLinkId, failed: true });
      }
    })();
    return () => controller.abort();
  }, [activeLinkId]);

  // **Derived, not cleared in an effect**, and the lint rule that forced this caught a real
  // defect. Clearing on a `null` link needed a `setState` inside the effect; carrying the link id
  // on the state instead means a *changed* link is also handled — the previous shape would have
  // rendered the old publication's alternatives for the moment between a correction landing and
  // the refetch returning, which is the one moment the list must not be wrong.
  const resolved =
    evidence !== null && evidence.linkId === activeLinkId && !("failed" in evidence)
      ? evidence
      : null;

  const submitCorrection = ({
    segmentId,
    reason,
    approverUsername,
    approverPassword,
  }: {
    segmentId: string;
    reason: string;
    approverUsername: string;
    approverPassword: string;
  }) => {
    if (phase.kind !== "ready" || resolved === null || active === null) return;
    setBusy(true);
    setNotice(null);

    // Two calls, in this order, and the reference is spent immediately. A recent-auth context is
    // single-use and short-lived, so obtaining one before the person has finished filling the
    // form would be holding something that expires while they type.
    void approverReauthenticate({
      username: approverUsername,
      password: approverPassword,
      actionClass: CORRECTION_PURPOSE,
      resourceType: CORRECTION_RESOURCE_TYPE,
      // Bound to the publication being superseded, so a step-up taken while looking at version 3
      // cannot correct version 4.
      resourceId: active.id,
    })
      .then((context) =>
        correctPublication(requestId, phase.ifMatch, {
          replacesEvidenceLinkId: resolved.link.id,
          newReceiptSegmentId: segmentId,
          correctionReason: reason,
          // The id the step-up route resolved, never a second lookup of the same username.
          approvedByAdminUserId: context.approverId,
          recentAuthReference: context.reference,
        }),
      )
      .then(async () => {
        setCorrecting(false);
        setPhase(await load());
      })
      .catch(async (caught: unknown) => {
        const status = (caught as { status?: number }).status;
        const body = (caught as { body?: { error?: { message?: string } } }).body?.error?.message;
        setNotice(
          status === 401
            ? t("correction.recentAuthFailed")
            : status === 412
              ? t("publication.stale")
              : (body ?? t("correction.failed")),
        );
        try {
          setPhase(await load());
        } catch {
          setPhase({ kind: "failed" });
        }
      })
      .finally(() => setBusy(false));
  };

  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    setNotice(null);
    try {
      await run();
      setPhase(await load());
    } catch (error) {
      const status = (error as { status?: number }).status;
      setNotice(status === 412 ? t("publication.stale") : t("publication.refused"));
      try {
        setPhase(await load());
      } catch {
        setPhase({ kind: "failed" });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <AdminShell>
      <section aria-labelledby="publication-heading" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-xl font-semibold" id="publication-heading">
            {t("publication.title")}
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

        {phase.kind === "failed" ? (
          <StateView
            description={t("publication.failed")}
            headingLevel={2}
            kind="error"
            title={t("publication.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            {notice !== null ? (
              <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
                {notice}
              </p>
            ) : null}

            <p className="text-sm">{t("publication.previewFirst")}</p>
            <button
              className="rounded border px-3 py-1"
              disabled={busy}
              onClick={() =>
                act(async () => {
                  setPreview(await previewPublication(requestId));
                })
              }
              type="button"
            >
              {t("publication.preview")}
            </button>

            {preview !== null ? (
              <div className="space-y-3 rounded border p-4">
                <dl className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <dt className="text-sm font-medium">{t("publication.nextVersion")}</dt>
                    <dd>{preview.next_publication_version}</dd>
                  </div>
                  <div>
                    {/* The hash of what would be published. Shown because it is the one value a
                        person can compare against what the trader later receives. */}
                    <dt className="text-sm font-medium">{t("publication.contentHash")}</dt>
                    <dd className="break-all text-xs">
                      <BidiText>{preview.content_hash}</BidiText>
                    </dd>
                  </div>
                </dl>

                {/* The redacted payload exactly as the trader will see it, rendered rather than
                    summarised: §16.7's whole purpose is that somebody reads it before it becomes
                    immutable, and a summary is a second opinion about its contents. */}
                <pre className="overflow-x-auto rounded bg-black/5 p-3 text-xs" dir="ltr">
                  {JSON.stringify(preview.summary_payload, null, 2)}
                </pre>

                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{t("publication.messageToTrader")}</span>
                  <textarea
                    className="rounded border px-2 py-1"
                    disabled={busy}
                    onChange={(event) => setMessage(event.target.value)}
                    rows={3}
                    value={message}
                  />
                </label>

                {/* Only after a preview. A publication is immutable and the flow that would
                    supersede it is blocked, so the preview is the last point at which this is
                    reversible. */}
                <button
                  className="rounded border px-3 py-1 font-bold"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      await publishResult(requestId, phase.ifMatch, {
                        messageToTrader: message.trim() || null,
                      });
                      setPreview(null);
                      setMessage("");
                    })
                  }
                  type="button"
                >
                  {t("publication.publish")}
                </button>
              </div>
            ) : null}

            <section aria-labelledby="history-heading" className="space-y-2">
              <h2 className="font-semibold" id="history-heading">
                {t("publication.historyTitle")}
              </h2>
              {phase.history.length === 0 ? (
                <p className="text-sm">{t("publication.historyEmpty")}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-start text-sm">
                    <thead>
                      <tr>
                        <th scope="col">{t("publication.version")}</th>
                        <th scope="col">{t("publication.status")}</th>
                        <th scope="col">{t("publication.publishedAt")}</th>
                        <th scope="col">{t("publication.contentHash")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {phase.history.map((publication) => (
                        <tr data-status={publication.status} key={publication.id}>
                          <td>{publication.publication_version}</td>
                          <td>
                            <BidiText>{publication.status}</BidiText>
                          </td>
                          <td>
                            <BidiText>{publication.published_at}</BidiText>
                          </td>
                          <td className="break-all text-xs">
                            <BidiText>{publication.content_hash}</BidiText>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/*
              The correction, which was a panel explaining its own absence until M0 slice A2.

              Three things had to be true and none of them were: a role had to hold the grants
              (the owner assigned them on 2026-09-08), the second human had to be able to prove
              presence (`approver-reauthenticate`, on the owner's decision of 2026-09-09), and the
              screen had to be able to *resolve* what a publication cites — `GET /evidence-links/
              {"{id}"}` and the bundle's segment list, neither of which the contract published.

              Shown only against an active publication. A request whose result has been superseded
              and not re-published has nothing to correct, and the server would refuse.
            */}
            {active === null ? null : correcting ? (
              <CorrectionDialog
                busy={busy}
                currentSegmentId={resolved?.link.receipt_segment_id ?? ""}
                error={notice}
                onCancel={() => {
                  setCorrecting(false);
                  setNotice(null);
                }}
                onSubmit={submitCorrection}
                segments={resolved?.segments ?? []}
              />
            ) : (
              <div className="mt-6">
                <button
                  className="rounded-lg border border-[var(--gold-700)] px-4 py-2 font-bold disabled:opacity-50"
                  data-testid="correction-open"
                  // Disabled rather than hidden while the evidence read is in flight or failed:
                  // a control that vanishes reads as a permission the person does not have, and
                  // `UI-NAV-001` is the standing rule that a hidden action is not a control.
                  disabled={busy || resolved === null}
                  onClick={() => {
                    setNotice(null);
                    setCorrecting(true);
                  }}
                  type="button"
                >
                  {t("correction.open")}
                </button>
                {evidence !== null && "failed" in evidence ? (
                  <p className="mt-2 text-sm text-[var(--ink-600)]" role="status">
                    {t("correction.evidenceUnavailable")}
                  </p>
                ) : null}
              </div>
            )}
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}
