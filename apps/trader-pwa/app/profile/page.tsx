"use client";

import { t } from "@gold/localization";
import { StateView } from "@gold/ui";
import { useEffect, useState } from "react";

import { TraderShell } from "../../components/trader-shell";
import { readOwnProfile, type OwnTraderProfile } from "../../src/profile";

/**
 * What a business sees about itself.
 *
 * This is the other half of the demonstration path: a trader registers, and until this
 * screen existed the only thing the platform told them afterwards was a success message
 * on a form they had already left. Now they can sign in and see where their application
 * stands — which is also the screen that shows the centre's decision arriving.
 *
 * **Two status axes, shown as one message.** `approval_status` is the centre's decision
 * about the business and `operational_status` is whether it may transact today
 * (DOC-CONFLICT-024). A suspended business is still an approved one, so the suspension is
 * what the reader needs to be told about — the approval is no longer the news.
 *
 * Nothing here is a control. The backend refuses a pending business its operable surface
 * on its own; this screen only explains the refusal in advance, so the reader is not left
 * to discover it by being turned away.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly profile: OwnTraderProfile }
  | { readonly kind: "failed" };

type Standing = Readonly<{ title: string; description: string; tone: "waiting" | "good" | "stopped" }>;

/**
 * The one message for a business, from both axes.
 *
 * Operational state is read first on purpose: a suspended business whose approval still
 * says "approved" needs to be told it cannot trade, and showing the approval instead
 * would be technically true and practically misleading.
 */
function standingFor(profile: OwnTraderProfile): Standing {
  if (profile.operational_status === "suspended") {
    return {
      title: t("trader.profile.suspendedTitle"),
      description: t("trader.profile.suspended"),
      tone: "stopped",
    };
  }
  if (profile.approval_status === "rejected") {
    return {
      title: t("trader.profile.rejectedTitle"),
      description: t("trader.profile.rejected"),
      tone: "stopped",
    };
  }
  if (profile.approval_status === "approved") {
    return {
      title: t("trader.profile.approvedTitle"),
      description: t("trader.profile.approved"),
      tone: "good",
    };
  }
  return {
    title: t("trader.profile.pendingTitle"),
    description: t("trader.profile.pending"),
    tone: "waiting",
  };
}

const toneClass: Record<Standing["tone"], string> = {
  waiting: "border-[var(--gold-500)] bg-[var(--gold-50)]",
  good: "border-[var(--border)] bg-[var(--surface)]",
  stopped: "border-[var(--border)] bg-[var(--surface-subtle)]",
};

export default function TraderProfilePage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  // State is set from the fetch's callback rather than after an await in the effect body:
  // `react-hooks/set-state-in-effect` refuses the second shape because an effect that
  // sets state synchronously can cascade renders. The abort is the other half — leaving
  // the page mid-request must not set state on a component that is gone.
  useEffect(() => {
    const controller = new AbortController();
    readOwnProfile(controller.signal)
      .then((profile) => setPhase({ kind: "ready", profile }))
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, [attempt]);

  return (
    <TraderShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("trader.profile.title")}</h1>

        {phase.kind === "loading" ? (
          <div className="mt-6">
            <StateView
              headingLevel={2}
              description={t("trader.profile.loading")}
              kind="loading"
              title={t("trader.profile.loading")}
            />
          </div>
        ) : null}

        {phase.kind === "failed" ? (
          <div className="mt-6">
            <StateView
              headingLevel={2}
              actions={
                <button
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-2 font-bold"
                  onClick={() => setAttempt((count) => count + 1)}
                  type="button"
                >
                  {t("trader.profile.refresh")}
                </button>
              }
              description={t("trader.profile.failed")}
              kind="error"
              title={t("trader.profile.failedTitle")}
            />
          </div>
        ) : null}

        {phase.kind === "ready" ? (
          <>
            <div
              className={`mt-6 rounded-2xl border p-5 leading-8 ${toneClass[standingFor(phase.profile).tone]}`}
              role="status"
            >
              <h2 className="text-xl font-black">{standingFor(phase.profile).title}</h2>
              <p className="mt-2 text-[var(--ink-600)]">{standingFor(phase.profile).description}</p>
            </div>

            <dl className="mt-6 grid gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-sm text-[var(--ink-600)]">{t("trader.profile.name")}</dt>
                <dd className="mt-1 font-bold">{phase.profile.display_name}</dd>
              </div>
              <div>
                <dt className="text-sm text-[var(--ink-600)]">{t("trader.profile.legalName")}</dt>
                <dd className="mt-1 font-bold">
                  {phase.profile.legal_name ?? t("trader.profile.notProvided")}
                </dd>
              </div>
              <div>
                <dt className="text-sm text-[var(--ink-600)]">{t("trader.profile.phone")}</dt>
                {/* Latin digits inside a right-to-left page: without the isolation the
                    leading `+` renders at the wrong end and the number reads as a
                    different one. */}
                <dd className="mt-1 font-bold" dir="ltr">
                  {phase.profile.primary_phone}
                </dd>
              </div>
            </dl>
          </>
        ) : null}
      </section>
    </TraderShell>
  );
}
