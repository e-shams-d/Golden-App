"use client";

import { normalizeDigits, t } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { TraderShell } from "../../../components/trader-shell";
import {
  createDraft,
  listBeneficiaries,
  type AmountUnit,
  type Beneficiary,
} from "../../../src/payment-requests";

/**
 * Opening a draft: which beneficiary, how much, and in which unit.
 *
 * **The unit is a choice, never an assumption, and the browser does no arithmetic.**
 * `15_Agent_Implementation_Plan.md:802` makes the server authoritative for the conversion,
 * so this screen sends the digits as typed together with the chosen unit and renders whatever
 * comes back. A field that quietly meant TOMAN, or a helper that multiplied by ten to "show
 * the real amount", would be a second implementation of the conversion — and the first time
 * the two disagreed a goldsmith would have authorised an amount they never typed.
 *
 * There is deliberately no live "= X ریال" preview for the same reason. It would be the
 * conversion, in the browser, wearing a label that says it is only a hint.
 *
 * **Persian digits are accepted and normalised, not rejected.** A goldsmith typing on a
 * Persian keyboard produces ۱۲۳, and `normalizeDigits` is what M3 built for exactly this.
 * Refusing their own numerals would be the application telling them to type like a machine.
 */

type Phase =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly beneficiaries: readonly Beneficiary[] }
  | { readonly kind: "failed" };

const ACTIVE = "active";

export default function NewTraderRequestPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [beneficiaryId, setBeneficiaryId] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState<AmountUnit>("TOMAN");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    listBeneficiaries(controller.signal)
      .then((all) => {
        const usable = all.filter((one) => one.status === ACTIVE);
        setPhase({ kind: "ready", beneficiaries: usable });
        // Preselect only when there is no choice to make. Preselecting the first of several
        // would put a destination on the form that nobody picked.
        if (usable.length === 1) setBeneficiaryId(usable[0]!.id);
      })
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, []);

  const save = async () => {
    setNotice(undefined);
    const digits = normalizeDigits(value).trim();
    if (!digits) {
      setNotice(t("trader.newRequest.amountRequired"));
      return;
    }

    setBusy(true);
    try {
      const created = await createDraft({
        beneficiaryId,
        // Sent as typed, in the unit chosen. No conversion here, by design.
        value: digits,
        unit,
        description: description.trim() || null,
      });
      router.push(`/requests/${created.request.id}`);
    } catch {
      setNotice(t("trader.newRequest.failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <TraderShell>
      <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-raised)]">
        <h1 className="text-3xl font-black">{t("trader.newRequest.title")}</h1>
        <p className="mt-3 max-w-3xl leading-8 text-[var(--ink-600)]">
          {t("trader.newRequest.description")}
        </p>

        {notice ? (
          <p
            className="mt-4 rounded-xl border border-[var(--gold-500)] bg-[var(--gold-50)] p-4 leading-7"
            role="alert"
          >
            {notice}
          </p>
        ) : null}

        {phase.kind === "loading" ? (
          <StateView
            headingLevel={2}
            description={t("trader.requests.loading")}
            kind="loading"
            title={t("trader.requests.loading")}
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
            actions={
              <Link
                className="rounded-lg bg-[var(--gold-700)] px-4 py-2 font-bold text-white"
                href="/beneficiaries"
              >
                {t("trader.newRequest.addBeneficiary")}
              </Link>
            }
            description={t("trader.newRequest.needsBeneficiary")}
            kind="empty"
            title={t("trader.beneficiaries.emptyTitle")}
          />
        ) : null}

        {phase.kind === "ready" && phase.beneficiaries.length > 0 ? (
          <form
            className="mt-6 flex max-w-2xl flex-col gap-5"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <label className="flex flex-col gap-2">
              <span className="font-bold">{t("trader.newRequest.beneficiary")}</span>
              <select
                className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
                onChange={(event) => setBeneficiaryId(event.target.value)}
                required
                value={beneficiaryId}
              >
                <option value="">—</option>
                {phase.beneficiaries.map((one) => (
                  <option key={one.id} value={one.id}>
                    {one.full_name}
                  </option>
                ))}
              </select>
              <span className="text-sm text-[var(--ink-600)]">
                {t("trader.newRequest.beneficiaryHint")}
              </span>
            </label>

            <div className="flex flex-wrap items-end gap-4">
              <label className="flex flex-1 flex-col gap-2">
                <span className="font-bold">{t("trader.newRequest.amount")}</span>
                {/* `inputMode="numeric"` rather than `type="number"`: a number input
                    rejects Persian digits outright, and these amounts are longer than a
                    float can carry without rounding. The value stays a string all the way
                    to the wire. */}
                <input
                  className="rounded-lg border border-[var(--border)] px-3 py-2"
                  dir="ltr"
                  inputMode="numeric"
                  onChange={(event) => setValue(event.target.value)}
                  required
                  type="text"
                  value={value}
                />
              </label>

              <label className="flex flex-col gap-2">
                <span className="font-bold">{t("trader.newRequest.unit")}</span>
                <select
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
                  onChange={(event) => setUnit(event.target.value as AmountUnit)}
                  value={unit}
                >
                  <option value="TOMAN">{t("money.unit.TOMAN")}</option>
                  <option value="IRR">{t("money.unit.IRR")}</option>
                </select>
              </label>
            </div>

            <label className="flex flex-col gap-2">
              <span className="font-bold">{t("trader.newRequest.note")}</span>
              <textarea
                className="rounded-lg border border-[var(--border)] px-3 py-2"
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
                value={description}
              />
            </label>

            <div>
              <button
                className="rounded-lg bg-[var(--gold-700)] px-6 py-3 font-bold text-white disabled:opacity-60"
                disabled={busy || !beneficiaryId}
                type="submit"
              >
                {busy ? t("trader.newRequest.working") : t("trader.newRequest.submit")}
              </button>
            </div>
          </form>
        ) : null}
      </section>
    </TraderShell>
  );
}
