"use client";

import { stateForError } from "@gold/api-client";
import { t } from "@gold/localization";
import { StateView, kindForApplicationState } from "@gold/ui";
import { useEffect, useState } from "react";

import { AdminShell } from "../../components/admin-shell";
import { listRoles, type Role } from "../../src/admin-users";

/**
 * What each role can do — read-only, and the read-only part is a decision.
 *
 * `PUT /roles/{id}/permissions` exists and this screen does not call it. Two reasons, and
 * the second is the one that matters:
 *
 * **A change requires a step-up context bound to this exact role**, obtained through
 * `POST /auth/reauthenticate` with `purpose: "role.permissions.update"`, `resource_type:
 * "role"` and this role's id.
 *
 * `adminAuthAdapter.reauthenticate` used to throw rather than send a placeholder binding,
 * because a context bound to nothing would authorise anything. **M7's screens slice 2
 * implemented it**, supplying the binding from the approval screen — so the obstacle this
 * paragraph described is gone, and what remains is the second reason below, which is not
 * about authentication at all.
 *
 * **And the route cannot remove a permission at all.** `role_permissions.py` refuses any
 * request that would drop one, because removing means deleting a `role_permissions` row and
 * `test_no_deletion_machinery.py` forbids every delete while ADR-005 is open. An editor
 * whose checkboxes could only ever be ticked would teach an operator something false about
 * the system in the first thirty seconds.
 *
 * So this shows what is true today: which role carries which permission, read from the
 * server. That is what makes the navigation gating in `src/navigation.ts` legible to
 * somebody being shown the platform — they can see *why* an accountant has no traders item.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly roles: readonly Role[] }
  | { readonly kind: "state"; readonly state: string };

export default function RolesPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    listRoles(controller.signal)
      .then((roles) => setPhase({ kind: "ready", roles }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const state = stateForError(error);
        if (state !== undefined) setPhase({ kind: "state", state });
      });
    return () => controller.abort();
  }, []);

  return (
    <AdminShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("roles.title")}</h1>
        <p className="mt-3 max-w-3xl leading-8 text-[var(--ink-600)]">{t("roles.description")}</p>
        <p className="mt-5 rounded-xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-4 leading-7">
          {t("roles.readOnlyNotice")}
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
            description={t("roles.failed")}
            headingLevel={2}
            kind={kindForApplicationState(phase.state)}
            title={t("roles.failedTitle")}
          />
        </div>
      ) : null}

      {phase.kind === "ready" ? (
        <ul className="mt-6 grid gap-4">
          {phase.roles.map((role) => (
            <li
              className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"
              key={role.id}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-black" dir="ltr">
                  {role.code}
                </h2>
                <span className="rounded-full border border-current px-3 py-1 text-sm font-bold">
                  {role.is_enabled ? t("roles.enabled") : t("roles.disabled")}
                </span>
              </div>
              {role.description ? (
                <p className="mt-2 leading-7 text-[var(--ink-600)]">{role.description}</p>
              ) : null}
              <p className="mt-3 text-sm font-bold">
                {t("roles.permissionCount").replace("{count}", String(role.permission_codes.length))}
              </p>
              {/* The codes themselves, in a scrolling region. An operator being shown why a
                  navigation item is missing needs to see the code, and a truncated list
                  would send them to the database to finish the sentence. */}
              <div className="mt-3 max-h-40 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--surface-subtle)] p-3">
                <ul className="grid gap-1 text-sm" dir="ltr">
                  {[...role.permission_codes].sort().map((code) => (
                    <li key={code}>{code}</li>
                  ))}
                </ul>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </AdminShell>
  );
}
