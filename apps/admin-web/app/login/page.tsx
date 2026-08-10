"use client";

import { t } from "@gold/localization";
import { LoginForm } from "@gold/ui";
import { useRouter } from "next/navigation";

import { login } from "../../src/auth";

/**
 * The internal login screen.
 *
 * The same component as the trader screen with different strings and a different
 * submit handler — and crucially not a different *branch*, because a shared handler
 * that chose a route would put both routes in both bundles. See `src/auth.ts`.
 *
 * There is no registration link here. Internal accounts are created by an
 * administrator (`05_API_Specification.md:868`), so a self-service path would
 * offer something that does not exist.
 */
export default function AdminLoginPage() {
  const router = useRouter();

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10" dir="rtl">
      <LoginForm
        failureMessage={t("login.failure")}
        identifierHint={t("admin.login.identifierHint")}
        identifierLabel={t("admin.login.identifier")}
        onSubmit={async (input) => {
          await login(input);
          router.refresh();
          router.replace("/");
        }}
        passwordLabel={t("login.password")}
        submitLabel={t("login.submit")}
        submittingLabel={t("login.submitting")}
        title={t("admin.login.title")}
      />
    </main>
  );
}
