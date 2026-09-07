"""Control 4: a warehouse queue points somewhere other than the order page.

The wrong screen for the right row. A warehouse operator following `blocked-dispatches` would land
on `/payment-attempts/<an order id>` — a 404 that reads as a stale link, or worse if the ids ever
collided.

This is the failure `detail_path` was built to prevent, and the reason the pairing is asserted as
an equality naming each queue *and where it goes* rather than as a count.
"""

import pathlib

QUEUES = pathlib.Path("services/backend/app/queues/manager_and_warehouse.py")

text = QUEUES.read_text(encoding="utf-8")
start = text.index("BLOCKED_DISPATCHES")
end = text.index("\n)\n", start)
block = text[start:end]
assert 'detail_path="/gold-orders"' in block, "the blocked queue no longer points at the order page"

text = text[:start] + block.replace(
    'detail_path="/gold-orders"', 'detail_path="/payment-attempts"', 1
) + text[end:]
QUEUES.write_text(text, encoding="utf-8")

assert 'detail_path="/payment-attempts"' in QUEUES.read_text(encoding="utf-8"), "DID NOT LAND"
print("control 4 applied: blocked-dispatches points at the attempt screen")
