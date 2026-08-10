"use client";

import { t } from "@gold/localization";
import { LoginForm } from "@gold/ui";
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
 */
export default function TraderLoginPage() {
  const router = useRouter();

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10" dir="rtl">
      <LoginForm
        failureMessage={t("login.failure")}
        footer={t("trader.login.registerPrompt")}
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
