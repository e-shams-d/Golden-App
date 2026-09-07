"""Control 2: the index counts through its own predicate instead of the queue's.

**A second definition of "waiting".** Not an error and not a crash — two plausible numbers. The
landing card and the queue page would agree today and diverge the first time a predicate narrowed,
which is the drift `visible_queues`'s delegation exists to make impossible.

Modelled as the cheapest wrong thing: count the entity's rows without applying the queue's
predicate at all. `orders-ready-for-dispatch` and `receipt-confirmation-work` both draw from
`gold_sale_orders` in different states, so an unpredicated count is *higher* than the queue's —
which is what makes the two surfaces disagree rather than merely both be wrong.
"""

import pathlib

MODULE = pathlib.Path("services/backend/app/queues/index.py")

BEFORE = "                waiting=count.waiting,\n"
AFTER = (
    "                waiting=_unpredicated(session, definition),\n"
)

HELPER = '''

def _unpredicated(session: Session, definition: Any) -> int:
    """The queue's table, counted without the queue's state predicate."""

    from sqlalchemy import func, select

    return int(session.execute(select(func.count()).select_from(definition.entity)).scalar() or 0)
'''

text = pathlib.Path(MODULE).read_text(encoding="utf-8")
assert BEFORE in text, "the waiting assignment is no longer written this way"
assert "_unpredicated" not in text, "already applied"

updated = text.replace(BEFORE, AFTER, 1)
updated = updated.replace(
    "from dataclasses import dataclass",
    "from dataclasses import dataclass\nfrom typing import Any",
    1,
)
updated = updated + HELPER
MODULE.write_text(updated, encoding="utf-8")

after = MODULE.read_text(encoding="utf-8")
assert "waiting=_unpredicated(session, definition)" in after, "THE EDIT DID NOT LAND"
assert "def _unpredicated(" in after, "THE EDIT DID NOT LAND"
print("control 2 applied: the index counts through its own statement")
