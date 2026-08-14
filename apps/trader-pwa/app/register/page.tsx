"use client";

import { ApiError } from "@gold/api-client";
import { t } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";
import { useId, useState, type FormEvent } from "react";

import { normalisePhone, registerTrader } from "../../src/registration";

/**
 * How a goldsmith asks to join.
 *
 * The last manual step in the demonstration path. Until this screen existed the only way
 * into the platform was a `curl` against `POST /traders/register`, which
 * `infra/scripts/rehearse-demo.sh` did and said so in a comment — a rehearsal that hides
 * a manual step is rehearsing a different performance than the one being given.
 *
 * **The success message does not say an account was created**, and that is the whole
 * design of this screen rather than a wording preference. The endpoint answers
 * `{accepted: true, pending_approval: true}` to a real registration and to a phone number
 * already registered, identically and on purpose: anything else would be a membership
 * oracle for the centre's customer list. So this screen is told nothing it could use to
 * distinguish them, and any message claiming a new account would be a claim it cannot
 * support. What it says instead — sign in with the number you entered to see where you
 * stand — is true in both cases, and lands the reader on `/profile`, which is where the
 * status actually lives.
 *
 * **The phone number is checked here because the server has decided not to.** An invalid
 * Iranian mobile is swallowed into the same acceptance (`app/api/v1/traders.py:253-256`),
 * so without this check a mistyped number produces a confident "you are in the queue" for
 * an application that was never written. The check is safe to do on the client precisely
 * because it is not a secret: the shape of a phone number is computable offline by
 * anybody. Membership is the part that stays the server's to refuse. See
 * `src/registration.ts` for the drift argument.
 *
 * **No password policy is invented here.** `app/security/passwords.py:25` says the
 * platform deliberately has no minimum length, no composition rules and no strength
 * meter. A form that added its own would be making a policy decision in the one place
 * nobody would look for it, and it would be enforced only for people who use the form.
 * The confirmation field is not a policy — it catches a typo in a value the person cannot
 * see and would otherwise discover at their first login attempt.
 */

type Phase =
  | { readonly kind: "editing" }
  | { readonly kind: "submitting" }
  | { readonly kind: "failed"; readonly rateLimited: boolean }
  | { readonly kind: "submitted" };

type FieldName = "displayName" | "contactFullName" | "primaryPhone" | "password" | "confirm";

type Problems = Partial<Record<FieldName, string>>;

const EMPTY = {
  displayName: "",
  legalName: "",
  contactFullName: "",
  primaryPhone: "",
  password: "",
  confirm: "",
};

/** Everything wrong with the form, in one pass.
 *
 * All of it at once rather than stopping at the first: a form that reveals its objections
 * one at a time makes somebody submit five times to learn five things.
 */
function inspect(values: typeof EMPTY): Problems {
  const problems: Problems = {};
  const required = t("trader.register.requiredField");

  if (!values.displayName.trim()) problems.displayName = required;
  if (!values.contactFullName.trim()) problems.contactFullName = required;
  if (!values.primaryPhone.trim()) problems.primaryPhone = required;
  else if (normalisePhone(values.primaryPhone) === null) {
    problems.primaryPhone = t("trader.register.invalidPhone");
  }
  if (!values.password) problems.password = required;
  if (values.password !== values.confirm) {
    problems.confirm = t("trader.register.passwordMismatch");
  }

  return problems;
}

export default function TraderRegisterPage() {
  const displayNameId = useId();
  const legalNameId = useId();
  const contactId = useId();
  const phoneId = useId();
  const passwordId = useId();
  const confirmId = useId();
  const summaryId = useId();

  const [values, setValues] = useState(EMPTY);
  const [problems, setProblems] = useState<Problems>({});
  const [phase, setPhase] = useState<Phase>({ kind: "editing" });

  function set(field: keyof typeof EMPTY, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (phase.kind === "submitting") return;

    const found = inspect(values);
    setProblems(found);
    if (Object.keys(found).length > 0) {
      setPhase({ kind: "editing" });
      return;
    }

    setPhase({ kind: "submitting" });
    try {
      await registerTrader({
        displayName: values.displayName.trim(),
        contactFullName: values.contactFullName.trim(),
        primaryPhone: values.primaryPhone.trim(),
        password: values.password,
        legalName: values.legalName.trim() || undefined,
      });
      // Cleared on success so a shared device does not keep a password in React state
      // behind a screen the person has finished with.
      setValues(EMPTY);
      setPhase({ kind: "submitted" });
    } catch (error) {
      // 429 is the one failure worth naming: it tells the person to wait rather than to
      // retype, and it is the only status this endpoint returns that a person can act on.
      // Every other reason renders the same, because the client knows no more.
      setPhase({ kind: "failed", rateLimited: error instanceof ApiError && error.status === 429 });
    }
  }

  if (phase.kind === "submitted") {
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-10" dir="rtl">
        <StateView
          actions={
            <Link
              className="rounded-lg bg-[var(--ink-950)] px-4 py-3 font-bold text-white"
              href="/login"
            >
              {t("trader.register.goToLogin")}
            </Link>
          }
          description={t("trader.register.done")}
          kind="empty"
          title={t("trader.register.doneTitle")}
        />
      </main>
    );
  }

  const submitting = phase.kind === "submitting";
  const listed = Object.values(problems).filter(Boolean);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10" dir="rtl">
      <form
        className="mx-auto w-full max-w-xl rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)] sm:p-8"
        noValidate
        onSubmit={handleSubmit}
      >
        <h1 className="text-2xl font-black">{t("trader.register.title")}</h1>
        <p className="mt-2 leading-7 text-[var(--ink-600)]">{t("trader.register.intro")}</p>

        {/* One summary at the top, because on a phone the field that was refused is often
            below the fold and a person who cannot see any objection concludes the button
            is broken. */}
        {listed.length > 0 ? (
          <div
            className="mt-6 rounded-xl border border-[var(--danger-500)] bg-[var(--danger-50)] p-4 leading-7"
            id={summaryId}
            role="alert"
          >
            <h2 className="font-black">{t("trader.register.problemsTitle")}</h2>
            <ul className="mt-2 list-disc pe-5">
              {listed.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {phase.kind === "failed" ? (
          <p
            className="mt-6 rounded-xl border border-[var(--danger-500)] bg-[var(--danger-50)] p-4 leading-7"
            role="alert"
          >
            {phase.rateLimited ? t("trader.register.rateLimited") : t("trader.register.failure")}
          </p>
        ) : null}

        <Field
          hint={t("trader.register.displayNameHint")}
          id={displayNameId}
          label={t("trader.register.displayName")}
          name="display_name"
          onChange={(value) => set("displayName", value)}
          problem={problems.displayName}
          required
          value={values.displayName}
        />

        <Field
          hint={t("trader.register.legalNameHint")}
          id={legalNameId}
          label={t("trader.register.legalName")}
          name="legal_name"
          onChange={(value) => set("legalName", value)}
          value={values.legalName}
        />

        <Field
          autoComplete="name"
          id={contactId}
          label={t("trader.register.contactName")}
          name="contact_full_name"
          onChange={(value) => set("contactFullName", value)}
          problem={problems.contactFullName}
          required
          value={values.contactFullName}
        />

        {/* `dir="ltr"` on the input inside a right-to-left page: a phone number is a
            left-to-right sequence, and typing `09123456789` into an RTL field puts the
            caret and the digits in an order that reads as the field being broken. */}
        <Field
          autoComplete="tel"
          direction="ltr"
          hint={t("trader.register.phoneHint")}
          id={phoneId}
          inputMode="tel"
          label={t("trader.register.phone")}
          name="primary_phone"
          onChange={(value) => set("primaryPhone", value)}
          problem={problems.primaryPhone}
          required
          value={values.primaryPhone}
        />

        <Field
          autoComplete="new-password"
          direction="ltr"
          hint={t("trader.register.passwordHint")}
          id={passwordId}
          label={t("trader.register.password")}
          name="password"
          onChange={(value) => set("password", value)}
          problem={problems.password}
          required
          type="password"
          value={values.password}
        />

        <Field
          autoComplete="new-password"
          direction="ltr"
          id={confirmId}
          label={t("trader.register.passwordConfirm")}
          name="password_confirm"
          onChange={(value) => set("confirm", value)}
          problem={problems.confirm}
          required
          type="password"
          value={values.confirm}
        />

        <button
          aria-busy={submitting}
          className="mt-8 w-full rounded-lg bg-[var(--ink-950)] px-4 py-3 font-bold text-white disabled:opacity-60"
          disabled={submitting}
          type="submit"
        >
          {submitting ? t("trader.register.submitting") : t("trader.register.submit")}
        </button>

        <p className="mt-6 text-[var(--ink-600)]">
          <Link className="underline" href="/login">
            {t("trader.register.backToLogin")}
          </Link>
        </p>
      </form>
    </main>
  );
}

type FieldProps = Readonly<{
  id: string;
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  problem?: string | undefined;
  required?: boolean;
  type?: "text" | "password";
  direction?: "ltr" | "rtl";
  autoComplete?: string;
  inputMode?: "text" | "tel";
}>;

/**
 * One labelled input, its hint and its objection.
 *
 * Extracted because six copies is six chances for one of them to lose the `htmlFor`, and
 * a label not tied to its input is invisible to a screen reader while looking correct on
 * screen — the failure mode that the a11y sweep exists to catch and that a reviewer's eye
 * does not.
 */
function Field({
  id,
  label,
  name,
  value,
  onChange,
  hint,
  problem,
  required = false,
  type = "text",
  direction = "rtl",
  autoComplete,
  inputMode,
}: FieldProps) {
  const hintId = `${id}-hint`;
  const problemId = `${id}-problem`;
  const describedBy = [hint ? hintId : null, problem ? problemId : null]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="mt-6">
      <label className="block font-bold" htmlFor={id}>
        {label}
      </label>
      {hint ? (
        <p className="mt-1 text-sm text-[var(--ink-600)]" id={hintId}>
          {hint}
        </p>
      ) : null}
      <input
        aria-describedby={describedBy || undefined}
        aria-invalid={problem ? true : undefined}
        autoComplete={autoComplete}
        className="mt-2 w-full rounded-lg border border-[var(--border)] bg-white px-4 py-3"
        dir={direction}
        id={id}
        inputMode={inputMode}
        name={name}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        type={type}
        value={value}
      />
      {problem ? (
        <p className="mt-2 text-sm font-bold text-[var(--danger-700)]" id={problemId}>
          {problem}
        </p>
      ) : null}
    </div>
  );
}
