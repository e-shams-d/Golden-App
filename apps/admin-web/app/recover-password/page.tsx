"use client";

import { t } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";
import { useState } from "react";

import { recoverAdminPassword } from "../../src/password";

/**
 * The way out of `recovery_required`, for the person who is in it.
 *
 * M0 slice F, and the last operation in this application with no screen.
 *
 * **The blocker turned out not to be the one recorded.** `NO_SCREEN` said this route was blocked on
 * the owner deciding how a person receives a recovery *token*, and "a form with nothing to type into
 * it is worse than no form". There is no token: the route takes a username, the temporary password
 * an administrator set, and the one its owner chooses. The temporary password is the thing handed
 * over, and `/admin-users` has been generating and displaying one since M11 slice 8. The owner's
 * decision of 2026-09-13 — another administrator generates it and gives it in person or by phone —
 * confirmed the flow that already existed rather than choosing a new one.
 *
 * That is the third slice running where the recorded reason was true in its own terms and was not
 * the blocker.
 *
 * **Outside the admin shell, and it must be.** `recovery_required` refuses authentication, so
 * somebody in that state cannot sign in to reach a screen that would let them out of it. This page
 * renders like `/login`: no navigation, no session panel, nothing that assumes a session.
 *
 * **The 401 is reported as the server means it.** Unknown username, wrong temporary password and an
 * account not awaiting recovery are one answer, deliberately — `12_Security_RBAC_Audit.md:403`, and
 * the route's own docstring explains that splitting them would make this a status oracle for the
 * centre's own staff at the moment those accounts are most exposed. So this screen says the three
 * things to check rather than guessing which one failed. A screen that said "wrong password" would
 * be inventing a distinction the server refused to make.
 *
 * **Success does not sign anybody in, and the screen says so.** The response is `recovered: true`
 * and no session: a credential somebody else chose never becomes access on its own. Telling a person
 * "done" and leaving them on a dead page would read as a failure, so this links to the sign-in.
 */

type Phase = { readonly kind: "idle" } | { readonly kind: "done" };

export default function RecoverPasswordPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [busy, setBusy] = useState(false);
  const [username, setUsername] = useState("");
  const [temporary, setTemporary] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const submit = async () => {
    setNotice(null);
    if (next !== again) {
      // The one check this screen owns, for `/password`'s reason: the server has no second field to
      // compare against, so a typo would leave somebody holding a password they cannot reproduce —
      // and this time with no working credential to try again with.
      setNotice(t("recover.mismatch"));
      return;
    }
    setBusy(true);
    try {
      await recoverAdminPassword(username.trim(), temporary, next);
      setTemporary("");
      setNext("");
      setAgain("");
      setPhase({ kind: "done" });
    } catch (error) {
      const status = (error as { status?: number }).status;
      // 429 is named because it is actionable — waiting works — while 401 is deliberately not
      // diagnosable and is reported as the three things to check.
      setNotice(status === 429 ? t("recover.tooMany") : t("recover.refused"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10" dir="rtl">
      <h1 className="text-2xl font-black">{t("recover.title")}</h1>

      {phase.kind === "done" ? (
        <StateView
          actions={
            // Without this the person is told "done" and left on a page that can do nothing else,
            // which reads as a failure. Recovery ends with a normal sign-in by design.
            <Link className="rounded-lg border px-4 py-2 font-bold" href="/login">
              {t("recover.goToLogin")}
            </Link>
          }
          description={t("recover.doneDescription")}
          headingLevel={2}
          kind="empty"
          title={t("recover.doneTitle")}
        />
      ) : (
        <section aria-labelledby="recover-form" className="mt-6 space-y-4">
          <h2 className="text-lg font-bold" id="recover-form">
            {t("recover.formHeading")}
          </h2>
          <p className="text-sm text-[var(--muted)]">{t("recover.explanation")}</p>

          {notice !== null ? (
            <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
              {notice}
            </p>
          ) : null}

          <label className="block text-sm">
            <span className="font-medium">{t("recover.username")}</span>
            <input
              autoComplete="username"
              className="mt-1 w-full rounded border p-2"
              data-testid="recover-username"
              disabled={busy}
              onChange={(event) => setUsername(event.target.value)}
              value={username}
            />
          </label>

          <label className="block text-sm">
            <span className="font-medium">{t("recover.temporary")}</span>
            <input
              // `current-password`: to a password manager this *is* the credential being replaced,
              // and labelling it `new-password` would offer to save the temporary one.
              autoComplete="current-password"
              className="mt-1 w-full rounded border p-2"
              data-testid="recover-temporary"
              disabled={busy}
              onChange={(event) => setTemporary(event.target.value)}
              type="password"
              value={temporary}
            />
            <span className="text-[var(--muted)]">{t("recover.temporaryHint")}</span>
          </label>

          <label className="block text-sm">
            <span className="font-medium">{t("recover.newPassword")}</span>
            <input
              autoComplete="new-password"
              className="mt-1 w-full rounded border p-2"
              data-testid="recover-new"
              disabled={busy}
              onChange={(event) => setNext(event.target.value)}
              type="password"
              value={next}
            />
          </label>

          <label className="block text-sm">
            <span className="font-medium">{t("recover.repeatPassword")}</span>
            <input
              autoComplete="new-password"
              className="mt-1 w-full rounded border p-2"
              data-testid="recover-again"
              disabled={busy}
              onChange={(event) => setAgain(event.target.value)}
              type="password"
              value={again}
            />
          </label>

          <button
            className="rounded border px-4 py-2 font-bold disabled:opacity-50"
            data-testid="recover-submit"
            disabled={
              busy || username.trim() === "" || temporary === "" || next === "" || again === ""
            }
            onClick={() => void submit()}
            type="button"
          >
            {busy ? t("recover.submitting") : t("recover.submit")}
          </button>

          <p className="text-sm">
            <Link className="underline" href="/login">
              {t("recover.backToLogin")}
            </Link>
          </p>
        </section>
      )}
    </main>
  );
}
