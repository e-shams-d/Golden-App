"""Control 5: the warehouse's confirmation queue points at the receipt review screen.

`receipt-confirmation-work` is the **warehouse's** queue over gold *orders*, guarded by
`gold_sale.dispatch`. Its rows are order ids. Pointing it at the receipt screen sends a warehouse
operator to `/incoming-payments/<an order id>`, which is either a 404 that reads as a stale link
or — if the ids ever collided — somebody else's work.

**The wrong screen for the right row**, which is the failure `detail_path` was built to prevent,
and the reason the pairing is asserted as an equality rather than a floor. The name is close
enough to the receipt queue's that this is the mistake somebody actually makes.
"""

import pathlib

QUEUES = pathlib.Path("services/backend/app/queues/money_movement.py")

text = QUEUES.read_text(encoding="utf-8")
anchor = "RECEIPT_CONFIRMATION_WORK"
assert anchor in text or True, "checked below"

path = pathlib.Path("services/backend/app/queues/manager_and_warehouse.py")
text = path.read_text(encoding="utf-8")
assert "RECEIPT_CONFIRMATION_WORK" in text, "the confirmation queue is not defined here"
assert "detail_path" not in text, "a queue here already carries a destination"

start = text.index("RECEIPT_CONFIRMATION_WORK")
end = text.index("\n)\n", start)
text = text[:end] + '\n    detail_path="/incoming-payments",' + text[end:]
path.write_text(text, encoding="utf-8")

assert 'detail_path="/incoming-payments"' in path.read_text(encoding="utf-8"), "DID NOT LAND"
print("control 5 applied: the warehouse queue points at the receipt screen")
