"use client";

import { normalizeDigits, t } from "@gold/localization";
import { StateView } from "@gold/ui";
import { useCallback, useEffect, useState } from "react";

import { TraderShell } from "../../components/trader-shell";
import {
  createBeneficiary,
  listBeneficiaries,
  type Beneficiary,
  type DuplicateWarning,
} from "../../src/payment-requests";

/**
 * The accounts a trader pays to, and the warning that does not block.
 *
 * **A duplicate is reported, not refused.** Slice 2 built it that way on purpose: two
 * beneficiaries can legitimately share a name, and an IBAN can legitimately be re-registered
 * after a correction, so refusing would stop real work to prevent a mistake the person is
 * better placed to judge. This screen therefore shows the new beneficiary as created *and*
 * names what it matched — a warning that hid the creation would leave the trader unsure
 * whether to try again.
 *
 * The IBAN goes through `normalizeDigits`: a goldsmith typing on a Persian keyboard produces
 * Persian numerals, and the backend's pattern is Latin. Rejecting their own digits would be
 * the application asking them to type like a machine.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly beneficiaries: readonly Beneficiary[] }
  | { readonly kind: "failed" };

export default function TraderBeneficiariesPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [fullName, setFullName] = useState("");
  const [iban, setIban] = useState("");
  const [nationalId, setNationalId] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | undefined>(undefined);
  const [duplicates, setDuplicates] = useState<readonly DuplicateWarning[]>([]);

  const refresh = useCallback(async () => {
    try {
      setPhase({ kind: "ready", beneficiaries: await listBeneficiaries() });
    } catch {
      setPhase({ kind: "failed" });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    listBeneficiaries(controller.signal)
      .then((beneficiaries) => setPhase({ kind: "ready", beneficiaries }))
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, []);

  const add = async () => {
    setNotice(undefined);
    setDuplicates([]);
    setBusy(true);
    try {
      const created = await createBeneficiary({
        fullName: fullName.trim(),
        iban: normalizeDigits(iban).trim().toUpperCase(),
        nationalId: normalizeDigits(nationalId).trim() || null,
      });
      setDuplicates(created.duplicate_warnings);
      setFullName("");
      setIban("");
      setNationalId("");
      await refresh();
    } catch {
      setNotice(t("trader.beneficiaries.addFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <TraderShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("trader.beneficiaries.title")}</h1>
        <p className="mt-3 max-w-3xl leading-8 text-[var(--ink-600)]">
          {t("trader.beneficiaries.description")}
        </p>

        {notice ? (
          <p
            className="mt-4 rounded-xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-4 leading-7"
            role="alert"
          >
            {notice}
          </p>
        ) : null}

        {duplicates.length > 0 ? (
          <section
            className="mt-4 rounded-2xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-5"
            role="status"
          >
            <h2 className="text-xl font-black">{t("trader.beneficiaries.duplicateTitle")}</h2>
            <p className="mt-2 leading-8">{t("trader.beneficiaries.duplicateBody")}</p>
            <ul className="mt-3 flex flex-col gap-2">
              {duplicates.map((warning) => (
                <li key={warning.beneficiary_id}>
                  <span className="font-bold">{warning.full_name}</span>
                  <span className="text-[var(--ink-600)]">
                    {" "}
                    — {t("trader.beneficiaries.matchedOn")} {warning.matched_on}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="mt-6 rounded-2xl border border-[var(--border)] p-5">
          <h2 className="text-xl font-black">{t("trader.beneficiaries.addTitle")}</h2>
          <form
            className="mt-4 flex max-w-2xl flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void add();
            }}
          >
            <label className="flex flex-col gap-2">
              <span className="font-bold">{t("trader.beneficiaries.fullName")}</span>
              <input
                className="rounded-lg border border-[var(--border)] px-3 py-2"
                onChange={(event) => setFullName(event.target.value)}
                required
                type="text"
                value={fullName}
              />
            </label>
            <label className="flex flex-col gap-2">
              <span className="font-bold">{t("trader.beneficiaries.iban")}</span>
              {/* Latin-digit identifier inside a right-to-left page: without `dir="ltr"` the
                  `IR` prefix renders at the wrong end and the account reads as another one. */}
              <input
                className="rounded-lg border border-[var(--border)] px-3 py-2 font-mono"
                dir="ltr"
                onChange={(event) => setIban(event.target.value)}
                required
                type="text"
                value={iban}
              />
            </label>
            <label className="flex flex-col gap-2">
              <span className="font-bold">{t("trader.beneficiaries.nationalId")}</span>
              <input
                className="rounded-lg border border-[var(--border)] px-3 py-2"
                dir="ltr"
                inputMode="numeric"
                onChange={(event) => setNationalId(event.target.value)}
                type="text"
                value={nationalId}
              />
            </label>
            <div>
              <button
                className="rounded-lg bg-[var(--gold-700)] px-6 py-3 font-bold text-white disabled:opacity-60"
                disabled={busy}
                type="submit"
              >
                {busy ? t("trader.beneficiaries.working") : t("trader.beneficiaries.add")}
              </button>
            </div>
          </form>
        </section>

        <div className="mt-6">
          {phase.kind === "loading" ? (
            <StateView
              headingLevel={2}
              description={t("trader.beneficiaries.loading")}
              kind="loading"
              title={t("trader.beneficiaries.loading")}
            />
          ) : null}

          {phase.kind === "failed" ? (
            <StateView
              headingLevel={2}
              description={t("trader.beneficiaries.failed")}
              kind="error"
              title={t("trader.beneficiaries.failedTitle")}
            />
          ) : null}

          {phase.kind === "ready" && phase.beneficiaries.length === 0 ? (
            <StateView
              headingLevel={2}
              description={t("trader.beneficiaries.empty")}
              kind="empty"
              title={t("trader.beneficiaries.emptyTitle")}
            />
          ) : null}

          {phase.kind === "ready" && phase.beneficiaries.length > 0 ? (
            <table className="w-full border-collapse text-start">
              <caption className="sr-only">{t("trader.beneficiaries.title")}</caption>
              <thead>
                <tr className="border-b border-[var(--border)] text-sm text-[var(--ink-600)]">
                  <th className="p-3 text-start" scope="col">
                    {t("trader.beneficiaries.name")}
                  </th>
                  <th className="p-3 text-start" scope="col">
                    {t("trader.beneficiaries.iban")}
                  </th>
                  <th className="p-3 text-start" scope="col">
                    {t("trader.beneficiaries.status")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {phase.beneficiaries.map((one) => (
                  <tr className="border-b border-[var(--border)]" key={one.id}>
                    <td className="p-3 font-bold">{one.full_name}</td>
                    <td className="p-3 font-mono" dir="ltr">
                      {one.iban}
                    </td>
                    <td className="p-3">{one.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      </section>
    </TraderShell>
  );
}
