"""Control 4: the landing panel keeps its own list of queues.

The drift the index route exists to prevent. A hardcoded list works perfectly on the day it is
written and its failure mode is a link to a queue the server no longer serves — or, worse, a queue
card a person may not read, since a list in the frontend cannot filter by grant.

Written as the shape somebody actually reaches for: keep calling the index, but render a fixed
order of names and look each one up. It *looks* like it is still using the server's answer.
"""

import pathlib

PANEL = pathlib.Path("apps/admin-web/components/queue-index.tsx")

BEFORE = "        {phase.items.map((listing) => (\n"
AFTER = (
    "        {[\n"
    '          "new-requests",\n'
    '          "eligible-for-batching",\n'
    '          "orders-ready-for-dispatch",\n'
    '          "quarantined-files-exports",\n'
    "        ]\n"
    "          .map((wanted) => phase.items.find((item) => item.name === wanted))\n"
    "          .filter((listing): listing is QueueListing => listing !== undefined)\n"
    "          .map((listing) => (\n"
)

text = PANEL.read_text(encoding="utf-8")
assert BEFORE in text, "the panel no longer maps the index items this way"
assert '"new-requests"' not in text, "already applied, or the panel already names a queue"

PANEL.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = PANEL.read_text(encoding="utf-8")
assert '"orders-ready-for-dispatch"' in after, "THE EDIT DID NOT LAND"
print("control 4 applied: the panel renders a hardcoded queue list")
