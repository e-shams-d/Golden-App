"""Control 2: the screen offers resolution codes of its own.

`TaskDetail.accepted_resolution_codes` is the catalogue's list, published on the row so a screen
offers what the command accepts. M8 built it for that reason and nothing had used it until slice 9.

A list written in the screen is the copy that drifts — and the drift is not cosmetic: a resolution
code the command refuses is a 400 in front of somebody finishing a piece of work, and one it
accepts but nobody expected is a row nothing can group afterwards. Grouping is what a queue is for.
"""

import pathlib

PAGE = pathlib.Path("apps/admin-web/app/review-tasks/[taskId]/page.tsx")

BEFORE = "                      {phase.task.accepted_resolution_codes.map((code) => (\n"
AFTER = '                      {["resolved", "no_action", "duplicate"].map((code) => (\n'

text = PAGE.read_text(encoding="utf-8")
assert BEFORE in text, "the resolution options are no longer rendered this way"

PAGE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = PAGE.read_text(encoding="utf-8")
assert '["resolved", "no_action", "duplicate"]' in after, "THE EDIT DID NOT LAND"
print("control 2 applied: the screen offers its own resolution codes")
