"""Control 1: the reconciliation queue's destination goes back to `None`.

**The state this slice found**, restored. The queue is built, permission-aware and on the
dashboard; its rows simply open nothing. An accountant sees that work is waiting and cannot do it,
and the count is a promise the software does not keep.

Nothing fails. No request errors. It was true for eleven milestones and the only reason anybody
noticed is that slice 8's gate asked which operations a person can reach.
"""

import pathlib

QUEUES = pathlib.Path("services/backend/app/queues/money_movement.py")

text = QUEUES.read_text(encoding="utf-8")
BEFORE = '    detail_path="/review-tasks",\n'
assert BEFORE in text, "the reconciliation queue no longer carries a destination"

QUEUES.write_text(text.replace(BEFORE, "", 1), encoding="utf-8")

after = QUEUES.read_text(encoding="utf-8")
assert '"/review-tasks"' not in after, "THE EDIT DID NOT LAND"
print("control 1 applied: the reconciliation queue opens nothing")
