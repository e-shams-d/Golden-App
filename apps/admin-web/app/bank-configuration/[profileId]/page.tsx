"use client";

import { stateForError } from "@gold/api-client";
import { t } from "@gold/localization";
import { BidiText, StateView, kindForApplicationState } from "@gold/ui";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../components/admin-shell";
import {
  activateBankProfileVersion,
  readBankProfile,
  type BankProfileDetail,
} from "../../../src/bank-configuration";

/**
 * One bank's configurations, and the one act that changes which rules apply.
 *
 * M0 slice B. **This screen is the reason slice B needed a backend change.** Activating a version
 * has been a published operation since M4 and was granted to `business_admin` on 2026-09-08 — and
 * it was still unreachable, because no read returned a profile's versions. The only `version_id`
 * obtainable anywhere was the one `POST /bank-profiles` answers with, so the only configuration
 * anybody could activate was one they had personally created moments earlier.
 *
 * **"In force" comes from the profile's own pointer, never from scanning statuses.**
 * `current_version_id` and the version rows must agree — `20260816_0014` moves them in one
 * transaction — and a screen that derived the live version by looking for `status === "active"`
 * would present its own second opinion as fact. When they disagree, that *is* the thing an
 * operator needs to see, so the two are rendered separately and the disagreement is visible.
 *
 * **No editing.** A version is immutable: superseded by inserting a new row, never updated, and
 * the runtime's grant covers `status` alone. Changing a bank's rules means a new version, and
 * `POST /bank-profiles/{id}/versions` is catalogued and not served — recorded in
 * `command_catalog.yaml`'s `path_note` against ADR-007, which needs a real bank file, per-
 * transaction limits and a cutoff time from the owner. The panel below says so rather than
 * offering a form that cannot work.
 *
 * **No `If-Match` on the activation.** The row has no `record_version` to be stale against and the
 * catalogue asks for a server-side lock; a precondition here would be invented.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly profile: BankProfileDetail }
  | { readonly kind: "state"; readonly state: string };

export default function BankProfilePage() {
  const parameters = useParams<{ profileId: string }>();
  const profileId = typeof parameters.profileId === "string" ? parameters.profileId : "";

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal): Promise<Phase> => ({
      kind: "ready",
      profile: await readBankProfile(profileId, signal),
    }),
    [profileId],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((next) => setPhase(next))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const state = stateForError(error);
        if (state !== undefined) setPhase({ kind: "state", state });
      });
    return () => controller.abort();
  }, [load]);

  const activate = (versionId: string) => {
    setBusy(true);
    setNotice(null);
    void activateBankProfileVersion(versionId)
      .then(async () => {
        setConfirming(null);
        setPhase(await load());
      })
      .catch(async (caught: unknown) => {
        const message = (caught as { body?: { error?: { message?: string } } }).body?.error
          ?.message;
        setNotice(message ?? t("bank.activateFailed"));
        try {
          setPhase(await load());
        } catch {
          /* the notice carries it; the list stays as it was */
        }
      })
      .finally(() => setBusy(false));
  };

  return (
    <AdminShell>
      <section aria-labelledby="bank-profile-heading" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-xl font-semibold" id="bank-profile-heading">
            {t("bank.profileTitle")}
          </h1>
          <Link className="rounded border px-3 py-1 text-sm" href="/bank-configuration">
            {t("bank.backToList")}
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

        {phase.kind === "state" ? (
          <StateView
            description={t("bank.failed")}
            headingLevel={2}
            kind={kindForApplicationState(phase.state)}
            title={t("bank.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            {notice !== null ? (
              <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
                {notice}
              </p>
            ) : null}

            <dl className="grid gap-3 sm:grid-cols-3">
              <div>
                <dt className="text-sm font-medium">{t("bank.displayName")}</dt>
                <dd>
                  <BidiText>{phase.profile.name}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("bank.code")}</dt>
                <dd>
                  <BidiText>{phase.profile.code}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("bank.inForce")}</dt>
                <dd data-testid="bank-current-version">
                  {/* The profile's pointer, rendered as the version *number* a person recognises
                      by resolving it against the list — and as "none" when the pointer is null,
                      which is a real state: a bank whose only configuration is still a draft. */}
                  {phase.profile.current_version_id === null ? (
                    <span>{t("bank.noneInForce")}</span>
                  ) : (
                    <BidiText>
                      {String(
                        phase.profile.versions.find(
                          (version) => version.id === phase.profile.current_version_id,
                        )?.version_number ?? t("bank.inForceUnknown"),
                      )}
                    </BidiText>
                  )}
                </dd>
              </div>
            </dl>

            <section aria-labelledby="bank-versions-heading" className="space-y-3">
              <h2 className="text-lg font-semibold" id="bank-versions-heading">
                {t("bank.versions")}
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-start text-sm" data-testid="bank-version-table">
                  <thead>
                    <tr>
                      <th scope="col">{t("bank.versionNumber")}</th>
                      <th scope="col">{t("bank.status")}</th>
                      <th scope="col">{t("bank.defaultLimit")}</th>
                      <th scope="col">{t("bank.afterCutoffLimit")}</th>
                      <th scope="col">{t("bank.cutoffTime")}</th>
                      <th scope="col">{t("bank.action")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {phase.profile.versions.map((version) => (
                      <tr data-status={version.status} key={version.id}>
                        <td>{version.version_number}</td>
                        <td>
                          <BidiText>{version.status}</BidiText>
                        </td>
                        {/* Rendered as the strings they arrive as. Nothing here parses a rial
                            figure into a JavaScript number; `MONEY_TIME_CONTRACT.md` rule 9. */}
                        <td>
                          <BidiText>{version.default_transfer_limit_irr ?? "—"}</BidiText>
                        </td>
                        <td>
                          <BidiText>{version.after_cutoff_transfer_limit_irr ?? "—"}</BidiText>
                        </td>
                        <td>
                          <BidiText>{version.cutoff_time ?? "—"}</BidiText>
                        </td>
                        <td>
                          {version.id === phase.profile.current_version_id ? (
                            <span>{t("bank.alreadyInForce")}</span>
                          ) : confirming === version.id ? (
                            <span className="flex flex-wrap items-center gap-2">
                              {/* Two clicks, because this changes how every payment built
                                  afterwards is shaped and there is no undo: superseding a version
                                  means activating another one. */}
                              <span>{t("bank.activateConfirm")}</span>
                              <button
                                className="rounded border px-2 py-1 font-bold disabled:opacity-50"
                                data-testid="bank-activate-confirm"
                                disabled={busy}
                                onClick={() => activate(version.id)}
                                type="button"
                              >
                                {busy ? t("bank.activating") : t("bank.activateYes")}
                              </button>
                              <button
                                className="rounded border px-2 py-1"
                                disabled={busy}
                                onClick={() => setConfirming(null)}
                                type="button"
                              >
                                {t("common.cancel")}
                              </button>
                            </span>
                          ) : (
                            <button
                              className="rounded border px-2 py-1 disabled:opacity-50"
                              data-testid="bank-activate"
                              disabled={busy}
                              onClick={() => {
                                setNotice(null);
                                setConfirming(version.id);
                              }}
                              type="button"
                            >
                              {t("bank.activate")}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {/* Why there is no "new version" form, said on the screen rather than left as a gap. */}
            <StateView
              description={t("bank.newVersionBlocked")}
              headingLevel={2}
              kind="empty"
              title={t("bank.newVersionBlockedTitle")}
            />
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}
