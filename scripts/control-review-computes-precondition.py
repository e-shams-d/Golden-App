"""Control 3: a command builds its precondition instead of echoing the read's.

`GET /manual-review-tasks/{task_id}` had no ETag until slice 5's contract-wide gate found three
routes missing one, and this screen is the first to use the one it gained. Computing
`rv-${record_version}` here would waste that and reintroduce the defect: a precondition that is
present, well-formed and compares a state nobody observed.

A shared queue is where it matters most — two people opening the same item is the normal case, not
the rare one.
"""

import pathlib

MODULE = pathlib.Path("apps/admin-web/src/review-tasks.ts")

BEFORE = """export async function startTask(taskId: string, ifMatch: string): Promise<ReviewTask> {
  const response = await transport.request<ReviewTask>({
    method: "POST",
    path: `/manual-review-tasks/${taskId}/start`,
    ifMatch,
  });"""

AFTER = """export async function startTask(taskId: string, ifMatch: string): Promise<ReviewTask> {
  const version = Number(ifMatch.replace(/\\D/gu, ""));
  const response = await transport.request<ReviewTask>({
    method: "POST",
    path: `/manual-review-tasks/${taskId}/start`,
    ifMatch: `"rv-${version}"`,
  });"""

text = MODULE.read_text(encoding="utf-8")
assert BEFORE in text, "the start command is no longer written this way"

MODULE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = MODULE.read_text(encoding="utf-8")
assert "rv-${version}" in after, "THE EDIT DID NOT LAND"
print("control 3 applied: the start command constructs its own precondition")
