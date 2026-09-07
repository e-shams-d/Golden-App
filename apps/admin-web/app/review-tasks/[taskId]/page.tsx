"use client";

import { t } from "@gold/localization";
import { BidiText, StateView } from "@gold/ui";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "../../../components/admin-shell";
import { listAdminUsers, type AdminUser } from "../../../src/admin-users";
import {
  assignTask,
  cancelTask,
  readTask,
  resolveTask,
  startTask,
  type ReviewTask,
} from "../../../src/review-tasks";

/**
 * One queue item, and the four decisions somebody may make about it. §22.1, §13.1.
 *
 * M11 Screens, slice 9 — closing the gap slice 8's own gate made visible. `reconciliation-tasks`
 * has been on the dashboard since slice 2 and its rows opened nothing: an accountant could see
 * that work was waiting and could not do it. **A queue that reports work nobody can reach is worse
 * than a missing one**, because the count is a promise.
 *
 * **The resolution codes are the server's**, published on the row as `accepted_resolution_codes`.
 * M8 put them there so a screen would offer what the command accepts, and nothing had used them —
 * this is the first screen to. A list written here would be the copy that drifts, and the
 * catalogue is where a resolution vocabulary belongs.
 *
 * **The subject is named, not fetched.** `entity_type` and `entity_id` are for navigation and
 * nothing else — §13.1 — and no read here joins through them. A screen that resolved them would be
 * a second way into a row, with its own guard to get wrong.
 */

type Phase =
  | { readonly kind: "loading" }
  | {
      readonly kind: "ready";
      readonly task: ReviewTask;
      readonly ifMatch: string;
      readonly staff: readonly AdminUser[];
    }
  | { readonly kind: "failed" };

/** The statuses from which work is still open. `06_Workflows` §13.1. */
const OPEN = new Set(["open", "in_progress"]);

export default function AdminReviewTaskPage() {
  const parameters = useParams<{ taskId: string }>();
  const taskId = typeof parameters.taskId === "string" ? parameters.taskId : "";

  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [assignee, setAssignee] = useState("");
  const [resolutionCode, setResolutionCode] = useState("");
  const [resolutionNote, setResolutionNote] = useState("");
  const [cancelReason, setCancelReason] = useState("");

  const load = useCallback(
    async (signal?: AbortSignal): Promise<Phase> => {
      const { task, ifMatch } = await readTask(taskId, signal);
      // The staff list is what an assignment needs a name from. Read here rather than typed as a
      // uuid: asking somebody to paste an id is asking them to get it wrong.
      const staff = await listAdminUsers(signal);
      return { kind: "ready", task, ifMatch, staff };
    },
    [taskId],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((next) => setPhase(next))
      .catch(() => {
        if (!controller.signal.aborted) setPhase({ kind: "failed" });
      });
    return () => controller.abort();
  }, [load]);

  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    setNotice(null);
    try {
      await run();
      setPhase(await load());
    } catch (error) {
      // 412 here means a colleague decided this item while it was open in front of somebody —
      // the case a shared queue makes ordinary rather than rare.
      const status = (error as { status?: number }).status;
      setNotice(status === 412 ? t("task.stale") : t("task.refused"));
      try {
        setPhase(await load());
      } catch {
        setPhase({ kind: "failed" });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <AdminShell>
      <section aria-labelledby="task-heading" className="space-y-4">
        <h1 className="text-xl font-semibold" id="task-heading">
          {t("task.title")}
        </h1>

        {phase.kind === "loading" ? (
          <StateView
            description={t("state.loading.description")}
            headingLevel={2}
            kind="loading"
            title={t("state.loading.title")}
          />
        ) : null}

        {phase.kind === "failed" ? (
          <StateView
            description={t("task.loadFailed")}
            headingLevel={2}
            kind="error"
            title={t("task.failedTitle")}
          />
        ) : null}

        {phase.kind === "ready" ? (
          <>
            <p className="font-medium">{phase.task.title}</p>
            {phase.task.description !== null ? (
              <p className="text-sm">{phase.task.description}</p>
            ) : null}

            <dl className="grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-sm font-medium">{t("task.status")}</dt>
                <dd>
                  <BidiText>{phase.task.status}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("task.type")}</dt>
                <dd>
                  <BidiText>{phase.task.task_type}</BidiText>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium">{t("task.assignedTo")}</dt>
                <dd>
                  {/* `null` is unassigned, which is not the same as assigned to nobody in
                      particular — it is the state the assign command exists to leave. */}
                  {phase.task.assigned_to === null ? (
                    <span>{t("task.unassigned")}</span>
                  ) : (
                    <BidiText>{phase.task.assigned_to}</BidiText>
                  )}
                </dd>
              </div>
              <div>
                {/* Named rather than resolved: §13.1 gives these for navigation and no read here
                    joins through them. */}
                <dt className="text-sm font-medium">{t("task.subject")}</dt>
                <dd className="break-all text-xs">
                  <BidiText>
                    {phase.task.entity_type} / {phase.task.entity_id}
                  </BidiText>
                </dd>
              </div>
              {phase.task.resolution_code !== null ? (
                <div>
                  <dt className="text-sm font-medium">{t("task.resolution")}</dt>
                  <dd>
                    <BidiText>{phase.task.resolution_code}</BidiText>
                    {phase.task.resolution_note !== null ? ` — ${phase.task.resolution_note}` : null}
                  </dd>
                </div>
              ) : null}
            </dl>

            {notice !== null ? (
              <p aria-live="assertive" className="rounded border p-3 text-sm" role="alert">
                {notice}
              </p>
            ) : null}

            {/* Absent once the item is answered: there is nothing a person can do to make a
                resolved task decidable again. */}
            {OPEN.has(phase.task.status) ? (
              <>
                <form
                  aria-labelledby="assign-heading"
                  className="space-y-2 rounded border p-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void act(() => assignTask(taskId, phase.ifMatch, assignee));
                  }}
                >
                  <h2 className="font-semibold" id="assign-heading">
                    {t("task.assignTitle")}
                  </h2>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="font-medium">{t("task.assignee")}</span>
                    <select
                      className="rounded border px-2 py-1"
                      disabled={busy}
                      onChange={(event) => setAssignee(event.target.value)}
                      required
                      value={assignee}
                    >
                      <option value="">{t("task.chooseAssignee")}</option>
                      {phase.staff.map((person) => (
                        <option key={person.id} value={person.id}>
                          {person.username}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button className="rounded border px-3 py-1 text-sm" disabled={busy} type="submit">
                    {t("task.assign")}
                  </button>
                </form>

                {phase.task.status === "open" ? (
                  <button
                    className="rounded border px-3 py-1"
                    disabled={busy}
                    onClick={() => act(() => startTask(taskId, phase.ifMatch))}
                    type="button"
                  >
                    {t("task.start")}
                  </button>
                ) : null}

                <form
                  aria-labelledby="resolve-heading"
                  className="space-y-2 rounded border p-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void act(() =>
                      resolveTask(
                        taskId,
                        phase.ifMatch,
                        resolutionCode,
                        resolutionNote.trim() || null,
                      ),
                    );
                  }}
                >
                  <h2 className="font-semibold" id="resolve-heading">
                    {t("task.resolveTitle")}
                  </h2>
                  {/* The server's vocabulary, not a list written here. A free-text resolution is
                      one nothing can group, and grouping is what a queue is for. */}
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="font-medium">{t("task.resolutionCode")}</span>
                    <select
                      className="rounded border px-2 py-1"
                      disabled={busy}
                      onChange={(event) => setResolutionCode(event.target.value)}
                      required
                      value={resolutionCode}
                    >
                      <option value="">{t("task.chooseResolution")}</option>
                      {phase.task.accepted_resolution_codes.map((code) => (
                        <option key={code} value={code}>
                          {code}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="font-medium">{t("task.resolutionNote")}</span>
                    <textarea
                      className="rounded border px-2 py-1"
                      disabled={busy}
                      onChange={(event) => setResolutionNote(event.target.value)}
                      rows={2}
                      value={resolutionNote}
                    />
                  </label>
                  <button className="rounded border px-3 py-1 text-sm" disabled={busy} type="submit">
                    {t("task.resolve")}
                  </button>
                </form>

                <form
                  aria-labelledby="cancel-heading"
                  className="space-y-2 rounded border p-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void act(() => cancelTask(taskId, phase.ifMatch, cancelReason));
                  }}
                >
                  <h2 className="font-semibold" id="cancel-heading">
                    {t("task.cancelTitle")}
                  </h2>
                  {/* Said before the field: cancelling ends the item without deciding it, which is
                      a different act from resolving and reads the same in a list afterwards. */}
                  <p className="text-sm">{t("task.cancelExplains")}</p>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="font-medium">{t("task.cancelReason")}</span>
                    <textarea
                      className="rounded border px-2 py-1"
                      disabled={busy}
                      onChange={(event) => setCancelReason(event.target.value)}
                      required
                      rows={2}
                      value={cancelReason}
                    />
                  </label>
                  <button className="rounded border px-3 py-1 text-sm" disabled={busy} type="submit">
                    {t("task.cancel")}
                  </button>
                </form>
              </>
            ) : null}
          </>
        ) : null}
      </section>
    </AdminShell>
  );
}
