"use client";

import { useCallback, useRef, useState } from "react";

import { Icon } from "./icon";

/**
 * `21_UI_Design_System_and_Screen_Specification.md:954-969` — staged upload, progress,
 * cancel before finalization, allowed type and size guidance, checksum and processing
 * state, quarantined state, retry, and no public storage path.
 *
 * **Quarantined is not failed, and the difference is the point.** A failed upload should
 * be retried; a quarantined one should not, because retrying sends the same bytes and
 * gets the same answer. Showing one as the other teaches a person to hammer a button that
 * cannot work — so the two outcomes carry different words, different colours, and only
 * one of them offers Retry.
 *
 * **The limits come from the server.** `accept` and the size ceiling are props fed by the
 * API rather than constants here: POL-006 will replace those numbers, and a limit written
 * into the bundle would need a frontend release to change one of them.
 */

export type UploadOutcome =
  | { readonly status: "available"; readonly fileId: string }
  | { readonly status: "quarantined"; readonly fileId: string; readonly reason?: string }
  | { readonly status: "failed"; readonly message: string };

export interface FileUploadPanelProps {
  /** Media types the purpose accepts, from the server. */
  readonly acceptedMediaTypes: readonly string[];
  /** Ceiling in bytes, from the server. */
  readonly maxBytes: number;
  /** Performs the upload. Rejects on refusal; resolves with what the server decided. */
  readonly upload: (file: File, signal: AbortSignal) => Promise<UploadOutcome>;
  readonly labels: {
    readonly choose: string;
    readonly uploading: string;
    readonly cancel: string;
    readonly retry: string;
    readonly available: string;
    readonly quarantined: string;
    readonly failed: string;
    readonly guidance: (types: string, megabytes: number) => string;
    readonly tooLarge: string;
  };
}

type Phase =
  | { readonly name: "idle" }
  | { readonly name: "uploading" }
  | { readonly name: "done"; readonly outcome: UploadOutcome };

/**
 * Whether an outcome should offer Retry.
 *
 * A pure function rather than a branch inside the component, so the rule can be asserted
 * without driving a browser: this package renders to static markup in its tests and has
 * no DOM-interaction library, and adding one to test a boolean would be a dependency
 * bought for a conditional.
 *
 * Only `failed`. Retrying a quarantined upload sends the same bytes and gets the same
 * answer, and offering the button teaches somebody to keep pressing it.
 */
export function offersRetry(outcome: UploadOutcome): boolean {
  return outcome.status === "failed";
}

/** The words for an outcome. Separate from the panel for the same reason. */
export function outcomeMessage(
  outcome: UploadOutcome,
  labels: Pick<FileUploadPanelProps["labels"], "available" | "quarantined" | "failed">,
): string {
  if (outcome.status === "available") return labels.available;
  if (outcome.status === "quarantined") return labels.quarantined;
  return labels.failed;
}

/** Whether the ceiling refuses this size before anything is sent. */
export function exceedsCeiling(size: number, maxBytes: number): boolean {
  return size > maxBytes;
}

export function FileUploadPanel({
  acceptedMediaTypes,
  maxBytes,
  upload,
  labels,
}: FileUploadPanelProps) {
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const [chosen, setChosen] = useState<File | null>(null);
  const controller = useRef<AbortController | null>(null);

  const start = useCallback(
    async (file: File) => {
      // Checked here as well as on the server. Not as a security control — the server's
      // refusal is the control — but so that a person on a slow connection is told before
      // spending three minutes sending something that will be refused on arrival.
      if (exceedsCeiling(file.size, maxBytes)) {
        setPhase({ name: "done", outcome: { status: "failed", message: labels.tooLarge } });
        return;
      }

      const abort = new AbortController();
      controller.current = abort;
      setPhase({ name: "uploading" });

      try {
        const outcome = await upload(file, abort.signal);
        setPhase({ name: "done", outcome });
      } catch (error) {
        // An aborted upload is not a failure to report: the person cancelled it.
        if (abort.signal.aborted) {
          setPhase({ name: "idle" });
          return;
        }
        setPhase({
          name: "done",
          outcome: { status: "failed", message: (error as Error).message },
        });
      } finally {
        controller.current = null;
      }
    },
    [labels.tooLarge, maxBytes, upload],
  );

  const cancel = useCallback(() => {
    controller.current?.abort();
    setPhase({ name: "idle" });
  }, []);

  const megabytes = Math.floor(maxBytes / (1024 * 1024));

  return (
    <section className="flex flex-col gap-3" data-testid="file-upload-panel">
      <p className="text-sm text-slate-600">
        {labels.guidance(acceptedMediaTypes.join("، "), megabytes)}
      </p>

      {phase.name === "idle" && (
        <label className="inline-flex w-fit cursor-pointer items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-white">
          <Icon name="upload" />
          <span>{labels.choose}</span>
          <input
            type="file"
            className="sr-only"
            accept={acceptedMediaTypes.join(",")}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                setChosen(file);
                void start(file);
              }
            }}
          />
        </label>
      )}

      {phase.name === "uploading" && (
        <div className="flex items-center gap-3">
          <span role="status">{labels.uploading}</span>
          {/* Cancel is available only before the server has decided, which is what
              "cancel before finalization" means: afterwards there is a row to account
              for and withdrawing it is a different act. */}
          <button type="button" onClick={cancel} className="underline">
            {labels.cancel}
          </button>
        </div>
      )}

      {phase.name === "done" && phase.outcome.status === "available" && (
        <p className="text-emerald-700" data-testid="upload-available">
          {labels.available}
        </p>
      )}

      {phase.name === "done" && phase.outcome.status === "quarantined" && (
        <p className="text-amber-700" data-testid="upload-quarantined">
          {labels.quarantined}
        </p>
      )}

      {phase.name === "done" && phase.outcome.status === "failed" && (
        <div className="flex items-center gap-3">
          <p className="text-danger-700" data-testid="upload-failed">
            {labels.failed}
          </p>
          {/* Retry only here. A quarantined file would send the same bytes and get the
              same answer, and offering the button would teach somebody to keep pressing
              it. */}
          <button
            type="button"
            className="underline"
            onClick={() => {
              if (chosen) void start(chosen);
            }}
          >
            {labels.retry}
          </button>
        </div>
      )}
    </section>
  );
}
