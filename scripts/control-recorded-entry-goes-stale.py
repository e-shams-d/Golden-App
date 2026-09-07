"""Control 4: a recorded entry stays after a screen reaches its operation.

The other direction, and the reason the list does not only grow. An entry whose paths a screen now
names is excusing nothing, and the next person reading it would believe part of the system is
unreachable when it is not — which is how a list of honest gaps turns into a list nobody trusts.

Modelled by naming the manual review path in a screen, which is what building that surface would
do.
"""

import pathlib

MODULE = pathlib.Path("apps/admin-web/src/queues.ts")

text = MODULE.read_text(encoding="utf-8")
assert "manual-review-tasks" not in text, "already applied"

ADDITION = """

export async function readReviewTask(taskId: string): Promise<unknown> {
  const response = await transport.request<unknown>({
    method: "GET",
    path: `/manual-review-tasks/${taskId}`,
  });
  return response.data;
}
"""

MODULE.write_text(text + ADDITION, encoding="utf-8")

after = MODULE.read_text(encoding="utf-8")
assert "manual-review-tasks" in after, "THE EDIT DID NOT LAND"
print("control 4 applied: a recorded operation now has a caller")
