"use client";

import { t } from "@gold/localization";
import { LoginForm } from "@gold/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { login } from "../../src/auth";

/**
 * The trader login screen.
 *
 * A client component because it holds the password in React state for the
 * duration of one submit and nowhere else. Nothing is written to `localStorage`
 * or `sessionStorage` — the session arrives as a `__Host-` prefixed HTTP-only
 * cookie this code cannot read, which is ADR-001's decision and what
 * `UI-STORE-001` checks.
 *
 * `router.refresh()` rather than a client-side redirect: the session is a cookie,
 * so the server can now answer as an authenticated caller, and asking it to
 * re-render is what makes that visible. A push to `/` with stale client state
 * would show the signed-out shell until something else happened to refetch.
 *
 * The footer has said "no account? apply to work with us" since it was written, and until
 * `/register` existed it was a sentence with nowhere to go. It is a link now — a prompt to
 * do something the interface offers no way to do is worse than no prompt, because the
 * reader concludes the page is broken rather than that the feature is missing.
 */
export default function TraderLoginPage() {
  const router = useRouter();

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10" dir="rtl">
      <LoginForm
        failureMessage={t("login.failure")}
        footer={
          <Link className="underline" href="/register">
            {t("trader.login.registerPrompt")}
          </Link>
        }
        identifierHint={t("trader.login.identifierHint")}
        identifierLabel={t("trader.login.identifier")}
        onSubmit={async (input) => {
          await login(input);
          router.refresh();
          router.replace("/");
        }}
        passwordLabel={t("login.password")}
        submitLabel={t("login.submit")}
        submittingLabel={t("login.submitting")}
        title={t("trader.login.title")}
      />
    </main>
  );
}
