"""Control 2: the centre is offered a trader's response.

Both routes are `trader_only(...)`, so an accountant pressing this gets a 403. On an internal
screen that reads as a permission problem — "ask an administrator for the grant" — rather than as
what it is: acknowledging a payment result on a customer's behalf is not a thing the centre may do,
and no grant exists that would make it one.

Modelled by dropping the audience condition, which is the shortest way to write the defect and the
most likely: `by_trader` looks like a convenience until you ask who the command belongs to.
"""

import pathlib

MODULE = pathlib.Path("services/backend/app/commands/payment_request.py")

BEFORE = "    if by_trader and status in trader_result.RESPONDABLE_FROM:\n"
AFTER = "    if status in trader_result.RESPONDABLE_FROM:\n"

text = MODULE.read_text(encoding="utf-8")
assert BEFORE in text, "the projection is no longer written this way; this control does not apply"

MODULE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = MODULE.read_text(encoding="utf-8")
assert AFTER in after and BEFORE not in after, "THE EDIT DID NOT LAND"
print("control 2 applied: staff are offered a trader's response")
