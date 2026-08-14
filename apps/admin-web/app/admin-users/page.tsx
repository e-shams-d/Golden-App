"use client";

import { stateForError } from "@gold/api-client";
import { t } from "@gold/localization";
import { StateView, kindForApplicationState } from "@gold/ui";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../components/admin-shell";
import {
  changeAdminUserState,
  createAdminUser,
  listAdminUsers,
  listRoles,
  readAdminUser,
  resetAdminUserPassword,
  type AdminUser,
  type Role,
} from "../../src/admin-users";

/**
 * Staff administration, which slice 8E built ten routes for and no way to reach.
 *
 * **Every write re-reads the account first.** The list is a snapshot, and between rendering
 * it and clicking a button another administrator may have acted. So each handler calls
 * `readAdminUser` and echoes the `ETag` that read returned — the `If-Match` is one request
 * old, never one page old. A 412 shows the stale-version state rather than retrying with a
 * fresher value, because a change the operator did not see the current state of is not
 * their change.
 *
 * **The state comes from `stateForError`**, the mapping slice 10C built and no screen used.
 * Eighteen application states, one table, and this is the first screen driven by it: a 403
 * is `permission-denied`, a 412 is `stale-version`, a 400 is `workflow-rejection`, and a
 * lost connection is `timeout-uncertain` rather than a failure — which matters here more
 * than anywhere, because a suspension whose outcome is unknown must not be retried blind.
 *
 * **Two refusals this screen surfaces rather than prevents.** The server refuses a
 * self-reset and refuses suspending the last account that can administer staff. Both are
 * business rules with reasons, and both arrive as a 400 whose message is written to be read
 * by an operator — so the message is rendered rather than replaced with a generic one.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready" }
  | { readonly kind: "state"; readonly state: string; readonly detail?: string };

const NEW_ACCOUNT = {
  username: "",
  fullName: "",
  password: "",
  roleCode: "accountant",
};

function statusLabel(value: string): string {
  const known: Record<string, string> = {
    active: t("status.active"),
    suspended: t("status.suspended"),
    recovery_required: t("adminUsers.status.recoveryRequired"),
    deactivated: t("adminUsers.status.deactivated"),
  };
  return known[value] ?? value;
}

export default function AdminUsersPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [accounts, setAccounts] = useState<readonly AdminUser[]>([]);
  const [roles, setRoles] = useState<readonly Role[]>([]);
  const [draft, setDraft] = useState(NEW_ACCOUNT);
  const [busyId, setBusyId] = useState<string | undefined>(undefined);
  const [notice, setNotice] = useState<string | undefined>(undefined);

  /** Every failure goes through the one mapping, with the server's message kept beside it. */
  const failed = (error: unknown): Phase => {
    const state = stateForError(error);
    // An abort is the caller's own navigation and is not a condition to render.
    if (state === undefined) return { kind: "ready" };
    const detail = (error as { message?: string }).message;
    return detail ? { kind: "state", state, detail } : { kind: "state", state };
  };

  const refresh = useCallback(async () => {
    try {
      const [loadedAccounts, loadedRoles] = await Promise.all([listAdminUsers(), listRoles()]);
      setAccounts(loadedAccounts);
      setRoles(loadedRoles);
      setPhase({ kind: "ready" });
    } catch (error) {
      setPhase(failed(error));
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([listAdminUsers(controller.signal), listRoles(controller.signal)])
      .then(([loadedAccounts, loadedRoles]) => {
        setAccounts(loadedAccounts);
        setRoles(loadedRoles);
        setPhase({ kind: "ready" });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setPhase(failed(error));
      });
    return () => controller.abort();
  }, []);

  async function submitNew(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice(undefined);
    try {
      const created = await createAdminUser({
        username: draft.username.trim(),
        fullName: draft.fullName.trim(),
        password: draft.password,
        roleCodes: [draft.roleCode],
      });
      // Cleared immediately: the password lived in React state for one submit and must not
      // survive it on a shared machine.
      setDraft(NEW_ACCOUNT);
      setNotice(t("adminUsers.created").replace("{username}", created.username));
      await refresh();
    } catch (error) {
      setPhase(failed(error));
    }
  }

  async function changeState(account: AdminUser, action: "suspend" | "reactivate") {
    setBusyId(account.id);
    setNotice(undefined);
    try {
      // Re-read, so the precondition is one request old rather than one page old.
      const { ifMatch } = await readAdminUser(account.id);
      const reason = action === "suspend" ? t("adminUsers.defaultSuspendReason") : undefined;
      await changeAdminUserState(account.id, action, ifMatch, reason);
      setNotice(t(action === "suspend" ? "adminUsers.suspended" : "adminUsers.reactivated"));
      await refresh();
    } catch (error) {
      setPhase(failed(error));
    } finally {
      setBusyId(undefined);
    }
  }

  async function resetPassword(account: AdminUser) {
    // Generated in the browser and shown once. The server returns nothing, which is the
    // obligation; somebody has to be able to read the value they are about to communicate,
    // and the only place it can be read is where it was chosen.
    const temporary = `Reset-${globalThis.crypto.randomUUID().slice(0, 12)}`;
    setBusyId(account.id);
    setNotice(undefined);
    try {
      const { ifMatch } = await readAdminUser(account.id);
      await resetAdminUserPassword(
        account.id,
        ifMatch,
        temporary,
        t("adminUsers.defaultResetReason"),
      );
      setNotice(t("adminUsers.resetDone").replace("{password}", temporary));
      await refresh();
    } catch (error) {
      setPhase(failed(error));
    } finally {
      setBusyId(undefined);
    }
  }

  return (
    <AdminShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("adminUsers.title")}</h1>
        <p className="mt-3 max-w-3xl leading-8 text-[var(--ink-600)]">
          {t("adminUsers.description")}
        </p>
      </section>

      {phase.kind === "loading" ? (
        <div className="mt-6">
          <StateView
            description={t("state.loading.description")}
            headingLevel={2}
            kind="loading"
            title={t("state.loading.title")}
          />
        </div>
      ) : null}

      {phase.kind === "state" ? (
        <div className="mt-6">
          <StateView
            actions={
              <button
                className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 font-bold"
                onClick={() => void refresh()}
                type="button"
              >
                {t("common.refresh")}
              </button>
            }
            // The server's own message when it wrote one for a person to read — the
            // last-administrator refusal and the self-reset refusal both do — and the
            // state's generic description otherwise.
            description={phase.detail ?? t("adminUsers.genericFailure")}
            headingLevel={2}
            kind={kindForApplicationState(phase.state)}
            title={t("adminUsers.actionFailed")}
          />
        </div>
      ) : null}

      {phase.kind === "ready" ? (
        <>
          {notice ? (
            <p
              className="mt-6 rounded-xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-4 leading-7"
              role="status"
            >
              {notice}
            </p>
          ) : null}

          <section aria-labelledby="accounts-heading" className="mt-6">
            <h2 className="text-xl font-black" id="accounts-heading">
              {t("adminUsers.listTitle")}
            </h2>

            {accounts.length === 0 ? (
              <div className="mt-4">
                <StateView
                  description={t("adminUsers.emptyDescription")}
                  headingLevel={3}
                  kind="empty"
                  title={t("adminUsers.emptyTitle")}
                />
              </div>
            ) : (
              <ul className="mt-4 grid gap-3">
                {accounts.map((account) => (
                  <li
                    className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"
                    key={account.id}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <p className="text-lg font-black">{account.full_name}</p>
                        <p className="mt-1 text-[var(--ink-600)]" dir="ltr">
                          {account.username}
                        </p>
                        <p className="mt-2 text-sm">
                          {t("adminUsers.roles")}: {account.role_codes.join("، ")}
                        </p>
                      </div>
                      <span className="rounded-full border border-current px-3 py-1 text-sm font-bold">
                        {statusLabel(account.status)}
                      </span>
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2">
                      {account.status === "suspended" ? (
                        <button
                          className="rounded-lg border border-[var(--border)] px-4 py-2 font-bold disabled:opacity-60"
                          disabled={busyId === account.id}
                          onClick={() => void changeState(account, "reactivate")}
                          type="button"
                        >
                          {t("adminUsers.reactivate")}
                        </button>
                      ) : (
                        <button
                          className="rounded-lg border border-[var(--danger-500)] px-4 py-2 font-bold text-[var(--danger-700)] disabled:opacity-60"
                          disabled={busyId === account.id}
                          onClick={() => void changeState(account, "suspend")}
                          type="button"
                        >
                          {t("adminUsers.suspend")}
                        </button>
                      )}
                      <button
                        className="rounded-lg border border-[var(--border)] px-4 py-2 font-bold disabled:opacity-60"
                        disabled={busyId === account.id}
                        onClick={() => void resetPassword(account)}
                        type="button"
                      >
                        {t("adminUsers.resetPassword")}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="create-heading" className="mt-8">
            <h2 className="text-xl font-black" id="create-heading">
              {t("adminUsers.createTitle")}
            </h2>
            <form
              className="mt-4 grid max-w-xl gap-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"
              onSubmit={(event) => void submitNew(event)}
            >
              <label className="grid gap-2 font-bold">
                {t("adminUsers.username")}
                <input
                  autoComplete="off"
                  className="rounded-lg border border-[var(--border)] bg-white px-4 py-3 font-normal"
                  dir="ltr"
                  name="username"
                  onChange={(event) => setDraft({ ...draft, username: event.target.value })}
                  required
                  value={draft.username}
                />
              </label>
              <label className="grid gap-2 font-bold">
                {t("adminUsers.fullName")}
                <input
                  className="rounded-lg border border-[var(--border)] bg-white px-4 py-3 font-normal"
                  name="full_name"
                  onChange={(event) => setDraft({ ...draft, fullName: event.target.value })}
                  required
                  value={draft.fullName}
                />
              </label>
              <label className="grid gap-2 font-bold">
                {t("adminUsers.password")}
                <input
                  autoComplete="new-password"
                  className="rounded-lg border border-[var(--border)] bg-white px-4 py-3 font-normal"
                  dir="ltr"
                  name="password"
                  onChange={(event) => setDraft({ ...draft, password: event.target.value })}
                  required
                  type="password"
                  value={draft.password}
                />
              </label>
              <label className="grid gap-2 font-bold">
                {t("adminUsers.role")}
                <select
                  className="rounded-lg border border-[var(--border)] bg-white px-4 py-3 font-normal"
                  name="role_code"
                  onChange={(event) => setDraft({ ...draft, roleCode: event.target.value })}
                  value={draft.roleCode}
                >
                  {/* From the server's own role list, not a literal. A screen offering a role
                      the deployment does not have would fail at submit with a message about
                      a code the operator never typed. */}
                  {roles.map((role) => (
                    <option key={role.id} value={role.code}>
                      {role.code}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="rounded-lg bg-[var(--ink-950)] px-4 py-3 font-bold text-white"
                type="submit"
              >
                {t("adminUsers.create")}
              </button>
            </form>
          </section>
        </>
      ) : null}
    </AdminShell>
  );
}
