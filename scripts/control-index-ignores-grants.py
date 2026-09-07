"""Control 1: the index returns every built queue, regardless of grant.

**The leak that looks like a working screen.** Every role would see all sixteen cards with real
counts, and nothing about the rendering would suggest anything is wrong — a warehouse operator
would simply also learn how much payment work the accountant has.

Written by replacing the delegation to `summarise_queues` with a loop over `BUILT` that never
consults `actor.permissions`, which is the shortest path to the defect and also the most likely
one: it is what somebody writes when the report's permission filtering is in the way.
"""

import pathlib

MODULE = pathlib.Path("services/backend/app/queues/index.py")

BEFORE = "    for count in summarise_queues(session, actor=actor).counts:\n"
AFTER = (
    "    from sqlalchemy import select\n\n"
    "    from app.queues.contract import read_queue_page\n\n"
    "    class _Count:\n"
    "        def __init__(self, queue: str, waiting: int) -> None:\n"
    "            self.queue = queue\n"
    "            self.waiting = waiting\n\n"
    "    _all = [\n"
    "        _Count(\n"
    "            name,\n"
    "            read_queue_page(\n"
    "                session, built, select(built.entity), actor=actor, limit=1\n"
    "            ).total,\n"
    "        )\n"
    "        for name, built in BUILT.items()\n"
    "    ]\n"
    "    for count in _all:\n"
)

text = MODULE.read_text(encoding="utf-8")
assert BEFORE in text, "the delegation is no longer written this way; this control does not apply"

MODULE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = MODULE.read_text(encoding="utf-8")
assert "for count in _all:" in after, "THE EDIT DID NOT LAND"
assert "summarise_queues(session, actor=actor).counts" not in after, "THE EDIT DID NOT LAND"
print("control 1 applied: the index no longer consults grants")
