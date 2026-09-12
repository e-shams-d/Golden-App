"use client";

import { stateForError } from "@gold/api-client";
import { t } from "@gold/localization";
import { BidiText, StateView, kindForApplicationState } from "@gold/ui";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../components/admin-shell";
import {
  createBankAccount,
  createBankProfile,
  listBankAccounts,
  listBankProfiles,
  type BankAccount,
  type BankProfileSummary,
} from "../../src/bank-configuration";

/**
 * The banks this centre pays through, and the accounts money leaves from.
 *
 * M0 slice B, and the reason it is second in the frontend completion plan: **if a bank changes a
 * transfer limit or a cutoff time, nobody can record it.** The profile, its versions and the
 * accounts existed only because a seed created them, and four published operations had no caller
 * in either application.
 *
 * **Creating a profile creates its first version too**, in one transaction — the composite
 * deferrable foreign key is what makes that possible, and a two-step write would leave a window in
 * which a reader sees a bank with no configuration at all. The form says so rather than presenting
 * two steps that are really one.
 *
 * **No editing, anywhere on this screen.** A `bank_profile_version` is immutable by construction:
 * superseded by inserting a new row, never updated, and the runtime's grant covers `status` alone.
 * A form that offered to change a limit would be offering something the database refuses. Changing
 * a bank's rules means a *new version* — and `POST /bank-profiles/{id}/versions` is catalogued and
 * not served, which `command_catalog.yaml`'s `path_note` now records against ADR-007. That is the
 * honest state and this screen does not paper over it.
 *
 * **Accounts are listed with masked IBANs** unless the caller holds `source_bank_account.manage`.
 * The masking is the server's; this renders what it is given. POL-003 has not settled who sees a
 * full account number, and a screen that unmasked locally would decide it.
 */

type Phase =
  | { readonly kind: "loading" }
  | {
      readonly kind: "ready";
      readonly profiles: readonly BankProfileSummary[];
      readonly accounts: readonly BankAccount[];
    }
  | { readonly kind: "state"; readonly state: string };

export default function BankConfigurationPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [profileForm, setProfileForm] = useState({
    code: "",
    displayName: "",
    defaultTransferLimitIrr: "",
    afterCutoffTransferLimitIrr: "",
    splittingEnabled: false,
    supportsDescriptionField: false,
  });
  const [accountForm, setAccountForm] = useState({
    profileId: "",
    displayName: "",
    accountRole: "outgoing_source",
    normalizedIban: "",
  });

  const load = useCallback(async (signal?: AbortSignal): Promise<Phase> => {
    const profiles = await listBankProfiles(signal);
    const accounts = await listBankAccounts(signal);
    return { kind: "ready", profiles, accounts };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((next) => setPhase(next))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const state = stateForError(error);
        if (state !== undefined) setPhase({ kind: "state", state });
      });
    return () => controller.abort();
  }, [load]);

  const act = (run: () => Promise<unknown>) => {
    setBusy(true);
    setNotice(null);
    void run()
      .then(async () => {
        setPhase(await load());
      })
      .catch(async (caught: unknown) => {
        const message = (caught as { body?: { error?: { message?: string } } }).body?.error
          ?.message;
        setNotice(message ?? t("bank.failed"));
        try {
          setPhase(await load());
        } catch {
          /* the notice already says what happened; the list stays as it was */
        }
      })
      .finally(() => setBusy(false));
  };

  return (
    <AdminShell>
      <section aria-labelledby="bank-heading" className="space-y-6">
        <h1 className="text-xl font-semibold" id="bank-heading">
          {t("bank.title")}
        </h1>

        {phase.kind === "loading" ? (
          <StateView
            description={t("state.loading.description")}
            headingLevel={2}
            kind="loading"
            title={t("state.loading.title")}
          />
        ) : null}

        {phase.kind === "state" ? (
          <StateView
            description={t("bank.failed")}
            headingLevel={2}
            kind={kindForApplicationState(phase.state)}
            title={t("bank.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            {notice !== null ? (
              <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
                {notice}
              </p>
            ) : null}

            <section aria-labelledby="bank-profiles-heading" className="space-y-3">
              <h2 className="text-lg font-semibold" id="bank-profiles-heading">
                {t("bank.profiles")}
              </h2>
              {phase.profiles.length === 0 ? (
                <StateView
                  description={t("bank.noProfiles")}
                  headingLevel={3}
                  kind="empty"
                  title={t("bank.noProfilesTitle")}
                />
              ) : (
                <ul className="space-y-2" data-testid="bank-profile-list">
                  {phase.profiles.map((profile) => (
                    <li className="rounded border p-3" key={profile.id}>
                      <Link
                        className="font-medium underline"
                        href={`/bank-configuration/${profile.id}`}
                      >
                        <BidiText>{profile.name}</BidiText>
                      </Link>
                      <span className="ms-3 text-sm text-[var(--ink-600)]">
                        <BidiText>{profile.code}</BidiText>
                      </span>
                      <span className="ms-3 text-sm">
                        <BidiText>{profile.status}</BidiText>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-labelledby="bank-new-profile-heading" className="space-y-3 rounded border p-4">
              <h2 className="text-lg font-semibold" id="bank-new-profile-heading">
                {t("bank.newProfile")}
              </h2>
              {/* Says what the command does, because it does two things and looks like one. */}
              <p className="text-sm text-[var(--ink-600)]">{t("bank.newProfileHint")}</p>

              <label className="block">
                <span className="font-bold">{t("bank.code")}</span>
                <input
                  className="mt-1 w-full rounded border p-2"
                  data-testid="bank-profile-code"
                  disabled={busy}
                  onChange={(event) =>
                    setProfileForm({ ...profileForm, code: event.target.value })
                  }
                  value={profileForm.code}
                />
              </label>

              <label className="block">
                <span className="font-bold">{t("bank.displayName")}</span>
                <input
                  className="mt-1 w-full rounded border p-2"
                  data-testid="bank-profile-name"
                  disabled={busy}
                  onChange={(event) =>
                    setProfileForm({ ...profileForm, displayName: event.target.value })
                  }
                  value={profileForm.displayName}
                />
              </label>

              <label className="block">
                <span className="font-bold">{t("bank.defaultLimit")}</span>
                {/* `inputMode="numeric"` and a text input, never `type="number"`: a rial figure is
                    a base-10 integer string on the wire and a number input invites a browser to
                    reformat, round, or offer scientific notation for one. */}
                <input
                  className="mt-1 w-full rounded border p-2"
                  data-testid="bank-profile-default-limit"
                  disabled={busy}
                  inputMode="numeric"
                  onChange={(event) =>
                    setProfileForm({ ...profileForm, defaultTransferLimitIrr: event.target.value })
                  }
                  value={profileForm.defaultTransferLimitIrr}
                />
                <span className="text-sm text-[var(--ink-600)]">{t("bank.limitBlankMeans")}</span>
              </label>

              <label className="block">
                <span className="font-bold">{t("bank.afterCutoffLimit")}</span>
                <input
                  className="mt-1 w-full rounded border p-2"
                  data-testid="bank-profile-cutoff-limit"
                  disabled={busy}
                  inputMode="numeric"
                  onChange={(event) =>
                    setProfileForm({
                      ...profileForm,
                      afterCutoffTransferLimitIrr: event.target.value,
                    })
                  }
                  value={profileForm.afterCutoffTransferLimitIrr}
                />
              </label>

              <label className="flex items-center gap-2">
                <input
                  checked={profileForm.splittingEnabled}
                  data-testid="bank-profile-splitting"
                  disabled={busy}
                  onChange={(event) =>
                    setProfileForm({ ...profileForm, splittingEnabled: event.target.checked })
                  }
                  type="checkbox"
                />
                <span>{t("bank.splittingEnabled")}</span>
              </label>

              <label className="flex items-center gap-2">
                <input
                  checked={profileForm.supportsDescriptionField}
                  data-testid="bank-profile-description-field"
                  disabled={busy}
                  onChange={(event) =>
                    setProfileForm({
                      ...profileForm,
                      supportsDescriptionField: event.target.checked,
                    })
                  }
                  type="checkbox"
                />
                <span>{t("bank.supportsDescription")}</span>
              </label>

              <button
                className="rounded border px-3 py-1 font-bold disabled:opacity-50"
                data-testid="bank-profile-create"
                disabled={
                  busy ||
                  profileForm.code.trim() === "" ||
                  profileForm.displayName.trim() === ""
                }
                onClick={() => act(() => createBankProfile(profileForm))}
                type="button"
              >
                {t("bank.createProfile")}
              </button>
            </section>

            <section aria-labelledby="bank-accounts-heading" className="space-y-3">
              <h2 className="text-lg font-semibold" id="bank-accounts-heading">
                {t("bank.accounts")}
              </h2>
              {phase.accounts.length === 0 ? (
                <StateView
                  description={t("bank.noAccounts")}
                  headingLevel={3}
                  kind="empty"
                  title={t("bank.noAccountsTitle")}
                />
              ) : (
                <ul className="space-y-2" data-testid="bank-account-list">
                  {phase.accounts.map((account) => (
                    <li className="rounded border p-3" key={account.id}>
                      <BidiText>{account.display_name}</BidiText>
                      <span className="ms-3 text-sm">
                        <BidiText>{account.account_role}</BidiText>
                      </span>
                      <span className="ms-3 font-mono text-sm">
                        <BidiText>{account.normalized_iban ?? "—"}</BidiText>
                      </span>
                      <span className="ms-3 text-sm">
                        <BidiText>{account.status}</BidiText>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-labelledby="bank-new-account-heading" className="space-y-3 rounded border p-4">
              <h2 className="text-lg font-semibold" id="bank-new-account-heading">
                {t("bank.newAccount")}
              </h2>

              <label className="block">
                <span className="font-bold">{t("bank.accountProfile")}</span>
                <select
                  className="mt-1 w-full rounded border p-2"
                  data-testid="bank-account-profile"
                  disabled={busy}
                  onChange={(event) =>
                    setAccountForm({ ...accountForm, profileId: event.target.value })
                  }
                  value={accountForm.profileId}
                >
                  <option value="">{t("bank.chooseProfile")}</option>
                  {phase.profiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="font-bold">{t("bank.displayName")}</span>
                <input
                  className="mt-1 w-full rounded border p-2"
                  data-testid="bank-account-name"
                  disabled={busy}
                  onChange={(event) =>
                    setAccountForm({ ...accountForm, displayName: event.target.value })
                  }
                  value={accountForm.displayName}
                />
              </label>

              <label className="block">
                <span className="font-bold">{t("bank.iban")}</span>
                <input
                  className="mt-1 w-full rounded border p-2 font-mono"
                  data-testid="bank-account-iban"
                  disabled={busy}
                  onChange={(event) =>
                    setAccountForm({ ...accountForm, normalizedIban: event.target.value })
                  }
                  value={accountForm.normalizedIban}
                />
              </label>

              <button
                className="rounded border px-3 py-1 font-bold disabled:opacity-50"
                data-testid="bank-account-create"
                disabled={
                  busy ||
                  accountForm.profileId === "" ||
                  accountForm.displayName.trim() === ""
                }
                onClick={() => act(() => createBankAccount(accountForm))}
                type="button"
              >
                {t("bank.createAccount")}
              </button>
            </section>
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}
