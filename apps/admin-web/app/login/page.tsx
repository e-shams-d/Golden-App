"use client";

import { t } from "@gold/localization";
import { LoginForm } from "@gold/ui";
import Link from "next/link";
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
 *
 * **M0 slice F puts the recovery link here and not in `LoginForm`**, which the trader screen also
 * renders. `POST /auth/admin/recover-password` is internal; a link inside the shared component
 * would put an admin path in the trader bundle — `UI-ISO-001` — and would offer a trader a flow
 * that does not exist for them.
 *
 * It belongs on *this* page because `recovery_required` refuses authentication: somebody just
 * handed a temporary password arrives here and finds nothing else to try. A recovery page nothing
 * linked to would be reachable only by typing a URL, which is the defect `UI-REQ-004` refuses.
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
      <p className="mt-6 text-sm">
        <Link className="underline" href="/recover-password">
          {t("recover.fromLogin")}
        </Link>
      </p>
    </main>
  );
}
