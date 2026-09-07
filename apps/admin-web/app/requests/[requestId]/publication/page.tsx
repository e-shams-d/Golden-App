"use client";

import { t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../../components/admin-shell";
import { readRequest } from "../../../../src/payment-requests";
import {
  listPublications,
  previewPublication,
  publishResult,
  type Publication,
  type PublicationPreview,
} from "../../../../src/payment-results";

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
 * **No correction control, and its absence is explained on the screen.**
 * `payment_publication.correct` is granted to no role: POL-002 splits preparer from approver and
 * defers the split to ADR-SEC-009, and the catalogue marks the command `method: TBD, path: TBD`.
 * A button would lead to a 403 for everybody. The panel says why in Persian rather than leaving a
 * person to conclude the software is broken.
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
              Why there is no correction control, said on the screen.

              `payment_publication.correct` is granted to no role — POL-002 splits preparer from
              approver and ADR-SEC-009 has not made the split — so a button would answer 403 to
              everybody. Left as a blank space, an accountant reading a wrong published result
              would conclude the software cannot fix it. It can; the authority to do so has not
              been assigned yet, and that is a different sentence.
            */}
            <StateView
              description={t("publication.correctionBlocked")}
              headingLevel={2}
              kind="empty"
              title={t("publication.correctionBlockedTitle")}
            />
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}
