"use client";

/**
 * The login form, shared as presentation and nothing else.
 *
 * It takes an `onSubmit` and knows no route, no audience and no endpoint. That is
 * what lets both apps use it without either bundle learning the other's login
 * path — `UI-ISO-001` checks the built output, and a shared component holding a
 * URL would put both URLs in both bundles.
 *
 * **One failure message, always.** The backend answers a single
 * `UNAUTHENTICATED` for an unknown identifier, a wrong password, a suspended
 * account and a locked one (`12_Security_RBAC_Audit.md:403`). The form renders
 * one message to match. Distinguishing them here would undo the server's care on
 * the client, and the client has no more information anyway — anything more
 * specific would be invented.
 *
 * **The identifier field is `dir="ltr"` inside a right-to-left page.** A phone
 * number and a username are left-to-right sequences; typing `09123456789` into an
 * RTL input puts the caret and the digits in an order that looks wrong to the
 * person entering it, which reads as the field being broken.
 */

import type { FormEvent, ReactNode } from "react";
import { useId, useState } from "react";

export type LoginFormProps = Readonly<{
  title: string;
  identifierLabel: string;
  identifierHint?: string;
  passwordLabel: string;
  submitLabel: string;
  submittingLabel: string;
  failureMessage: string;
  onSubmit: (input: { identifier: string; password: string }) => Promise<void>;
  footer?: ReactNode;
}>;

export function LoginForm({
  title,
  identifierLabel,
  identifierHint,
  passwordLabel,
  submitLabel,
  submittingLabel,
  failureMessage,
  onSubmit,
  footer,
}: LoginFormProps) {
  const identifierId = useId();
  const passwordId = useId();
  const errorId = useId();

  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [state, setState] = useState<"idle" | "submitting" | "failed">("idle");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state === "submitting") return;
    setState("submitting");
    try {
      await onSubmit({ identifier, password });
    } catch {
      // Every reason renders the same. The password is cleared and the
      // identifier kept: retyping a long phone number after a typo in the
      // password is the most common way a real user meets this screen.
      setPassword("");
      setState("failed");
    }
  }

  const submitting = state === "submitting";

  return (
    <form
      className="mx-auto w-full max-w-md rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)] sm:p-8"
      noValidate
      onSubmit={handleSubmit}
    >
      <h1 className="text-2xl font-black">{title}</h1>

      {state === "failed" ? (
        <p
          className="mt-4 rounded-xl border border-[var(--danger-500)] bg-[var(--danger-50)] p-4 leading-7"
          id={errorId}
          role="alert"
        >
          {failureMessage}
        </p>
      ) : null}

      <div className="mt-6">
        <label className="block font-bold" htmlFor={identifierId}>
          {identifierLabel}
        </label>
        {identifierHint ? (
          <p className="mt-1 text-sm text-[var(--ink-600)]">{identifierHint}</p>
        ) : null}
        <input
          aria-describedby={state === "failed" ? errorId : undefined}
          autoComplete="username"
          className="mt-2 w-full rounded-lg border border-[var(--border)] bg-white px-4 py-3"
          dir="ltr"
          id={identifierId}
          name="identifier"
          onChange={(event) => setIdentifier(event.target.value)}
          required
          value={identifier}
        />
      </div>

      <div className="mt-4">
        <label className="block font-bold" htmlFor={passwordId}>
          {passwordLabel}
        </label>
        <input
          aria-describedby={state === "failed" ? errorId : undefined}
          autoComplete="current-password"
          className="mt-2 w-full rounded-lg border border-[var(--border)] bg-white px-4 py-3"
          dir="ltr"
          id={passwordId}
          name="password"
          onChange={(event) => setPassword(event.target.value)}
          required
          type="password"
          value={password}
        />
      </div>

      <button
        aria-busy={submitting}
        className="mt-6 w-full rounded-lg bg-[var(--ink-950)] px-4 py-3 font-bold text-white disabled:opacity-60"
        disabled={submitting}
        type="submit"
      >
        {submitting ? submittingLabel : submitLabel}
      </button>

      {footer ? <div className="mt-6 text-[var(--ink-600)]">{footer}</div> : null}
    </form>
  );
}
