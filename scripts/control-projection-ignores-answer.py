"""Control 1: the projection keeps offering both responses after one has been given.

**The screen and the server disagree, and only the customer finds out.** `allowed_actions` would
report acknowledge on an already-acknowledged result, the screen would render the button, and
pressing it earns a 400 — a person pressing a button that does not work, with nothing failing
anywhere a developer would look.

Modelled as the mistake somebody actually makes: widen the state check to "anything after a result
was published", which reads as more generous and is simply wrong.
"""

import pathlib

MODULE = pathlib.Path("services/backend/app/commands/payment_request.py")

BEFORE = "    if by_trader and status in trader_result.RESPONDABLE_FROM:\n"
AFTER = (
    "    if by_trader and status in (\n"
    "        *trader_result.RESPONDABLE_FROM,\n"
    "        trader_result.REQUEST_ACKNOWLEDGED,\n"
    "        trader_result.REQUEST_DISPUTED,\n"
    "    ):\n"
)

text = MODULE.read_text(encoding="utf-8")
assert BEFORE in text, "the projection is no longer written this way; this control does not apply"

MODULE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = MODULE.read_text(encoding="utf-8")
assert "trader_result.REQUEST_ACKNOWLEDGED," in after, "THE EDIT DID NOT LAND"
print("control 1 applied: answered results still offer both responses")
