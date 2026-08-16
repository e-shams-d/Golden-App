"use client";

import { FileUploadPanel, SecureFileViewer, type UploadOutcome } from "@gold/ui";
import { useCallback, useState } from "react";

import { TraderShell } from "../../components/trader-shell";
import { RECEIPT_LIMITS, loadFileBytes, uploadReceipt } from "../../src/evidence";

/**
 * Where a goldsmith attaches a payment receipt, and sees it back.
 *
 * **This screen exists so the two components have a caller that is not a test.** M3 shipped
 * five mechanisms that were complete, tested and imported nowhere, and M4's own plan makes
 * the same demand of its frontend: a component with only an acceptance test is a component
 * nobody has actually used. `apps/trader-pwa/test/evidence-screen.test.tsx` asserts that
 * this file imports both.
 *
 * The upload lands in `quarantined` on any deployment without a scanner configured, which
 * is every deployment today. That is not a failure and the panel says so in different
 * words — a person told their receipt failed will send it again, and a person told it is
 * held for review will ask somebody.
 */

export default function EvidencePage() {
  const [uploaded, setUploaded] = useState<string | null>(null);

  const upload = useCallback(async (file: File, signal: AbortSignal): Promise<UploadOutcome> => {
    const result = await uploadReceipt(file, signal);
    if (result.status === "available") {
      setUploaded(result.id);
      return { status: "available", fileId: result.id };
    }
    // Quarantined is the ordinary outcome while no scanner is configured, so the id is
    // kept either way: the uploader may still read back what they sent, which is how they
    // check they sent the right thing.
    setUploaded(result.id);
    return { status: "quarantined", fileId: result.id };
  }, []);

  return (
    <TraderShell>
      <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-6">
        <h1 className="text-xl font-semibold">رسید پرداخت</h1>

        <FileUploadPanel
          acceptedMediaTypes={RECEIPT_LIMITS.acceptedMediaTypes}
          maxBytes={RECEIPT_LIMITS.maxBytes}
          upload={upload}
          labels={{
            choose: "انتخاب فایل",
            uploading: "در حال ارسال…",
            cancel: "انصراف",
            retry: "تلاش دوباره",
            available: "رسید ثبت شد.",
            quarantined: "رسید ثبت شد و برای بررسی نگه داشته شده است. کاری لازم نیست.",
            failed: "ارسال انجام نشد.",
            tooLarge: "حجم فایل بیش از حد مجاز است.",
            guidance: (types, megabytes) => `فرمت‌های مجاز: ${types} — حداکثر ${megabytes} مگابایت`,
          }}
        />

        {uploaded !== null && (
          <section className="flex flex-col gap-2">
            <h2 className="text-lg">پیش‌نمایش</h2>
            <SecureFileViewer
              fileId={uploaded}
              load={loadFileBytes}
              labels={{
                loading: "در حال بارگذاری…",
                processing: "در حال آماده‌سازی پیش‌نمایش…",
                expired: "این فایل در دسترس نیست.",
                retry: "تلاش دوباره",
                alt: "رسید بارگذاری‌شده",
              }}
            />
          </section>
        )}
      </main>
    </TraderShell>
  );
}
