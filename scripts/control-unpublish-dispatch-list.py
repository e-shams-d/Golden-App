"""Control 3: the dispatch list stops being published.

The acknowledge route then names a `{dispatch_id}` that no trader can obtain — a **path parameter
with no source**, which is the defect slice 7 found and which slice 5's precondition gate could not
see: that one asks where an `If-Match` comes from, and this is the same shape one level over.

Removing the route rather than breaking it, because a 500 would be caught by anything.
"""

import pathlib

ROUTER = pathlib.Path("services/backend/app/api/v1/gold_sale_orders.py")

text = ROUTER.read_text(encoding="utf-8")
marker = '@router.get(\n    "/{order_id}/dispatches",'
assert marker in text, "the dispatch list is no longer registered this way"

start = text.index(marker)
end = text.index('@router.post(\n    "/{order_id}/dispatches/{dispatch_id}/acknowledge"', start)
ROUTER.write_text(text[:start] + text[end:], encoding="utf-8")

after = ROUTER.read_text(encoding="utf-8")
assert "listGoldDispatches" not in after, "THE EDIT DID NOT LAND"
print("control 3 applied: the dispatch list route is gone")
