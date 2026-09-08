"use client";

import { t } from "@gold/localization";
import { StateView } from "@gold/ui";
import { useState } from "react";

import { AdminShell } from "../../components/admin-shell";
import { changeOwnPassword } from "../../src/password";

/**
 * Changing your own password.
 *
 * M11 Screens, slice 10 — the surface slice 8's gate recorded as missing. Somebody signing in for
 * the first time had no way to replace the password they were given.
 *
 * **The confirmation field is checked here and nowhere else**, and that is the one piece of
 * validation this screen owns: the server has no second field to compare against, so a typo in a
 * new password would lock somebody out of an account they had just changed. Everything else — the
 * old password being right, the new one being acceptable — is the server's, and the screen reports
 * what it says rather than predicting it.
 *
 * **A wrong current password is named as such.** The route answers 403 for that specific case, and
 * telling somebody their *new* password was rejected when what failed was the old one is the kind
 * of message that costs a support call.
 */

type Phase = { readonly kind: "idle" } | { readonly kind: "done" };

export default function AdminPasswordPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [busy, setBusy] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const submit = async () => {
    setNotice(null);
    if (next !== again) {
      // The one check this screen owns: the server has no second field to compare against, so a
      // typo here would lock somebody out of the account they had just changed.
      setNotice(t("password.mismatch"));
      return;
    }
    setBusy(true);
    try {
      await changeOwnPassword(current, next);
      setCurrent("");
      setNext("");
      setAgain("");
      setPhase({ kind: "done" });
    } catch (error) {
      const status = (error as { status?: number }).status;
      setNotice(status === 403 ? t("password.wrongCurrent") : t("password.failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AdminShell>
      <section aria-labelledby="password-heading" className="space-y-4">
        <h1 className="text-xl font-semibold" id="password-heading">
          {t("password.title")}
        </h1>
        <p className="text-sm">{t("password.explains")}</p>

        {phase.kind === "done" ? (
          <StateView
            description={t("password.doneDescription")}
            headingLevel={2}
            kind="empty"
            title={t("password.doneTitle")}
          />
        ) : null}

        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">{t("password.current")}</span>
            <input
              autoComplete="current-password"
              className="rounded border px-2 py-1"
              disabled={busy}
              onChange={(event) => setCurrent(event.target.value)}
              required
              type="password"
              value={current}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">{t("password.next")}</span>
            <input
              autoComplete="new-password"
              className="rounded border px-2 py-1"
              disabled={busy}
              onChange={(event) => setNext(event.target.value)}
              required
              type="password"
              value={next}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">{t("password.again")}</span>
            <input
              autoComplete="new-password"
              className="rounded border px-2 py-1"
              disabled={busy}
              onChange={(event) => setAgain(event.target.value)}
              required
              type="password"
              value={again}
            />
          </label>

          {notice !== null ? (
            <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
              {notice}
            </p>
          ) : null}

          <button className="rounded border px-3 py-1 font-bold" disabled={busy} type="submit">
            {t("password.submit")}
          </button>
        </form>
      </section>
    </AdminShell>
  );
}
