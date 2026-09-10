"use client";

import { t } from "@gold/localization";
import { BidiText } from "@gold/ui";
import { useState } from "react";

import type { ReceiptSegment } from "../src/payment-results";

/**
 * Correcting a published result, and the one dialog in this application that asks two people.
 *
 * §8.11's recent-auth dialog, with the difference that made this screen wait for an owner
 * decision: **the password belongs to the approver, not to the person typing everything else.**
 * `command_catalog.yaml` gives this command `recent_auth: "required_for_approving_second_human"`,
 * and the mechanism that existed could only prove the *caller* was present. The owner decided on
 * 2026-09-09 that the second human types their own password here, at this machine.
 *
 * **The username field is not decoration.** The correction body names an approver id, and the
 * server compares it against the id the step-up was bound to. Asking for the username here means
 * one person's credentials are entered once and travel together; a screen that let the preparer
 * pick a manager from a list and then asked "their password" would let a mistyped choice and a
 * correct password produce a context bound to somebody who never agreed to anything.
 *
 * **The current segment is shown and cannot be chosen.** A correction whose replacement is the
 * segment already published is refused by the server — `uq_evidence_link_attempt_segment_type`
 * refuses a second link for a pair that already has one — so offering it would be offering a
 * choice that always fails. It is rendered as context rather than hidden, because "which crop is
 * wrong" is the question the person is answering.
 *
 * **`onSubmit` gets the four values and nothing else.** The parent owns the `If-Match` and the
 * link id, the same way `DecisionDialog` keeps the captured content hash out of the component:
 * what a dialog cannot see, it cannot send a stale version of.
 */

export function CorrectionDialog({
  busy,
  currentSegmentId,
  error,
  onCancel,
  onSubmit,
  segments,
}: {
  /** True while the two calls are in flight. The dialog stays open and disabled. */
  readonly busy: boolean;
  /** What is published now. Shown, never selectable. */
  readonly currentSegmentId: string;
  /** What the server said, if it refused. Rendered as given; the server writes for a person. */
  readonly error: string | null;
  readonly onCancel: () => void;
  readonly onSubmit: (input: {
    readonly segmentId: string;
    readonly reason: string;
    readonly approverUsername: string;
    readonly approverPassword: string;
  }) => void;
  /** Every segment of the bundle the published evidence came from. */
  readonly segments: readonly ReceiptSegment[];
}) {
  const [segmentId, setSegmentId] = useState("");
  const [reason, setReason] = useState("");
  const [approverUsername, setApproverUsername] = useState("");
  const [approverPassword, setApproverPassword] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  const choices = segments.filter((segment) => segment.id !== currentSegmentId);

  // Every field, and the confirmation. §13.5's argument for the checkbox applies here with more
  // force than it does to an approval: this changes a number a trader has already been told.
  const ready =
    segmentId.length > 0 &&
    reason.trim().length > 0 &&
    approverUsername.trim().length > 0 &&
    approverPassword.length > 0 &&
    confirmed;

  return (
    <div
      aria-labelledby="correction-dialog-title"
      aria-modal="true"
      className="mt-6 rounded-2xl border-2 border-[var(--gold-700)] bg-[var(--surface)] p-5"
      data-testid="correction-dialog"
      role="dialog"
    >
      <h2 className="text-2xl font-black" id="correction-dialog-title">
        {t("correction.title")}
      </h2>
      <p className="mt-2 leading-8 text-[var(--ink-600)]">{t("correction.body")}</p>

      <p className="mt-4 text-sm text-[var(--ink-600)]">
        {t("correction.currentEvidence")}{" "}
        <BidiText>
          <span className="break-all font-mono text-xs" data-testid="correction-current-segment">
            {currentSegmentId}
          </span>
        </BidiText>
      </p>

      {choices.length === 0 ? (
        <p
          className="mt-4 rounded-lg border border-[var(--border)] p-3"
          data-testid="correction-no-alternatives"
          role="status"
        >
          {t("correction.noAlternatives")}
        </p>
      ) : (
        <fieldset className="mt-4">
          <legend className="font-bold">{t("correction.chooseEvidence")}</legend>
          <div className="mt-2 space-y-2">
            {choices.map((segment) => (
              <label className="flex items-start gap-2" key={segment.id}>
                <input
                  checked={segmentId === segment.id}
                  data-testid="correction-segment-choice"
                  disabled={busy}
                  name="correction-segment"
                  onChange={() => setSegmentId(segment.id)}
                  type="radio"
                  value={segment.id}
                />
                <span className="text-sm">
                  <BidiText>
                    <span className="break-all font-mono text-xs">{segment.id}</span>
                  </BidiText>
                  {/* The status and the privacy check, because a segment that has not been
                      reviewed is refused by the command and this is where a person can see that
                      before spending a manager's time on it. */}
                  <span className="ms-2">
                    <BidiText>{segment.status}</BidiText>
                  </span>
                  {segment.privacy_verified ? null : (
                    <span className="ms-2 text-[var(--danger-600)]">
                      {t("correction.privacyUnverified")}
                    </span>
                  )}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      <label className="mt-4 block">
        <span className="font-bold">{t("correction.reasonLabel")}</span>
        <textarea
          className="mt-1 w-full rounded-lg border border-[var(--border)] p-2"
          data-testid="correction-reason"
          disabled={busy}
          onChange={(event) => setReason(event.target.value)}
          required
          rows={3}
          value={reason}
        />
      </label>

      <fieldset className="mt-5 rounded-lg border border-[var(--border)] p-3">
        {/* The second human. `12_Security_RBAC_Audit.md:1345` requires that an accountant
            prepares and a second authorised human approves; the two ids differing is checked by
            the command, and this is what proves the second one was actually here. */}
        <legend className="font-bold">{t("correction.approverLegend")}</legend>
        <p className="text-sm text-[var(--ink-600)]">{t("correction.approverHint")}</p>

        <label className="mt-3 block">
          <span className="font-bold">{t("correction.approverUsername")}</span>
          <input
            autoComplete="off"
            className="mt-1 w-full rounded-lg border border-[var(--border)] p-2"
            data-testid="correction-approver-username"
            disabled={busy}
            onChange={(event) => setApproverUsername(event.target.value)}
            type="text"
            value={approverUsername}
          />
        </label>

        <label className="mt-3 block">
          <span className="font-bold">{t("correction.approverPassword")}</span>
          <input
            // `new-password` rather than `current-password`: this is not the signed-in person's
            // credential, and offering the browser's saved password for *this* account would
            // invite the preparer to submit their own and wonder why it was refused.
            autoComplete="new-password"
            className="mt-1 w-full rounded-lg border border-[var(--border)] p-2"
            data-testid="correction-approver-password"
            disabled={busy}
            onChange={(event) => setApproverPassword(event.target.value)}
            type="password"
            value={approverPassword}
          />
        </label>
      </fieldset>

      <label className="mt-4 flex items-start gap-2">
        <input
          checked={confirmed}
          data-testid="correction-confirm"
          disabled={busy}
          onChange={(event) => setConfirmed(event.target.checked)}
          type="checkbox"
        />
        <span>{t("correction.confirm")}</span>
      </label>

      {error ? (
        <p
          className="mt-4 rounded-lg border border-[var(--danger-600)] bg-[var(--danger-50)] p-3"
          data-testid="correction-error"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <div className="mt-5 flex flex-wrap gap-3">
        <button
          className="rounded-lg bg-[var(--gold-700)] px-4 py-2 font-bold text-white disabled:opacity-50"
          data-testid="correction-submit"
          disabled={busy || !ready}
          onClick={() => onSubmit({ segmentId, reason, approverUsername, approverPassword })}
          type="button"
        >
          {busy ? t("correction.working") : t("correction.submit")}
        </button>
        <button
          className="rounded-lg border border-[var(--border)] px-4 py-2 font-bold"
          disabled={busy}
          onClick={onCancel}
          type="button"
        >
          {t("common.cancel")}
        </button>
      </div>
    </div>
  );
}
