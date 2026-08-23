"use client";

import { t } from "@gold/localization";
import { useState } from "react";

/**
 * The approve and reject dialogs. §13.5 and §13.6 of the screen specification.
 *
 * **The hash and the version id are captured when the dialog opens and never re-read.** §13.5
 * requires an "expected content hash", and that requirement is only meaningful if the value is
 * the one the manager was looking at. A dialog that read the current hash at submit time would be
 * approving whatever is current — which after a replacement is not what was reviewed — and the
 * server would accept it, because the hash it was sent would match. `UI-APPROVE-001`.
 *
 * They are **props**, not state read from a parent that might refresh. That is `UI-STALE-002`:
 * §13.4's last clause says an open dialog must not be transferred to the new version, and the
 * cheapest way to guarantee that is for the dialog to have no way of learning about one. If the
 * page discovers it is stale it unmounts this component; it does not update it.
 *
 * **The UI updates only after authoritative server success.** §13.5's closing line. `onDecided`
 * is called with the server's response and nothing is assumed before it — an optimistic update
 * here would show an approval that did not happen, on the one screen where that matters most.
 */

export type DecisionKind = "approve" | "reject";

export function DecisionDialog({
  busy,
  error,
  kind,
  onCancel,
  onSubmit,
}: {
  /** True while the command is in flight. The dialog stays open and disabled. */
  readonly busy: boolean;
  /** What the server said, if it refused. Rendered as given; the server writes for a person. */
  readonly error: string | null;
  readonly kind: DecisionKind;
  readonly onCancel: () => void;
  /**
   * The password is the step-up challenge, and `reason` is required for a rejection.
   *
   * The parent owns the request because it owns the captured hash — this component never sees it,
   * so it cannot send a different one.
   */
  readonly onSubmit: (input: { password: string; reason: string }) => void;
}) {
  const [password, setPassword] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  // §13.5 requires "explicit confirmation" alongside the recent authentication. A password field
  // alone is a habit; a checkbox somebody has to tick is a decision. `UI-REJECT-001` makes the
  // reason mandatory for a rejection, which the button below enforces rather than the server
  // discovering it.
  const ready =
    password.length > 0 && confirmed && (kind === "approve" || reason.trim().length > 0);

  return (
    <div
      aria-labelledby="decision-dialog-title"
      aria-modal="true"
      className="mt-6 rounded-2xl border-2 border-[var(--gold-700)] bg-[var(--surface)] p-5"
      data-testid={`decision-dialog-${kind}`}
      role="dialog"
    >
      <h2 className="text-2xl font-black" id="decision-dialog-title">
        {kind === "approve" ? t("admin.decide.approveTitle") : t("admin.decide.rejectTitle")}
      </h2>
      <p className="mt-2 leading-8 text-[var(--ink-600)]">
        {kind === "approve" ? t("admin.decide.approveBody") : t("admin.decide.rejectBody")}
      </p>

      {kind === "reject" ? (
        <label className="mt-4 block">
          <span className="font-bold">{t("admin.decide.reasonLabel")}</span>
          <textarea
            className="mt-1 w-full rounded-lg border border-[var(--border)] p-2"
            data-testid="decision-reason"
            disabled={busy}
            onChange={(event) => setReason(event.target.value)}
            required
            rows={3}
            value={reason}
          />
        </label>
      ) : null}

      <label className="mt-4 block">
        {/* The step-up. `12_Security_RBAC_Audit.md:512`: a valid session is not sufficient
            assurance for this. It proves whoever holds the session was present a moment ago. */}
        <span className="font-bold">{t("admin.decide.passwordLabel")}</span>
        <input
          autoComplete="current-password"
          className="mt-1 w-full rounded-lg border border-[var(--border)] p-2"
          data-testid="decision-password"
          disabled={busy}
          onChange={(event) => setPassword(event.target.value)}
          type="password"
          value={password}
        />
      </label>

      <label className="mt-4 flex items-start gap-2">
        <input
          checked={confirmed}
          data-testid="decision-confirm"
          disabled={busy}
          onChange={(event) => setConfirmed(event.target.checked)}
          type="checkbox"
        />
        <span>
          {kind === "approve" ? t("admin.decide.confirmApprove") : t("admin.decide.confirmReject")}
        </span>
      </label>

      {error ? (
        <p
          className="mt-4 rounded-lg border border-[var(--danger-600)] bg-[var(--danger-50)] p-3"
          data-testid="decision-error"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <div className="mt-5 flex flex-wrap gap-3">
        <button
          className="rounded-lg bg-[var(--gold-700)] px-4 py-2 font-bold text-white disabled:opacity-50"
          data-testid="decision-submit"
          disabled={busy || !ready}
          onClick={() => onSubmit({ password, reason })}
          type="button"
        >
          {busy ? t("admin.decide.working") : t("admin.decide.submit")}
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
