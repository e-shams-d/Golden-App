"""Control 4: the screen invents a dispute-reason taxonomy.

**The one that nearly shipped**, which is why it is here rather than a hypothetical. The first
draft of this screen offered `amount_mismatch`, `not_received`, `wrong_beneficiary` and `other`,
none of which any catalogue names.

`app/commands/trader_result.py` left `reason_code` un-enumerated deliberately: *"A closed list
invented here would refuse a trader whose complaint does not fit one of the options somebody
guessed — and this is the only surface in the system whose user is a customer rather than staff,
so the cost of that is a phone call instead of a record."*

The server accepts anything, so **the screen's list becomes that closed list**, arriving through a
different door and with no review. Nothing fails: every dispute is accepted, every code is stored,
and the harm is a category a customer's complaint had to be squeezed into.
"""

import pathlib

PAGE = pathlib.Path("apps/trader-pwa/app/requests/[requestId]/result/page.tsx")

BEFORE = '  { code: "beneficiary_did_not_receive", label: "notReceived" },\n'
AFTER = (
    '  { code: "beneficiary_did_not_receive", label: "notReceived" },\n'
    '  { code: "amount_mismatch", label: "notReceived" },\n'
    '  { code: "wrong_beneficiary", label: "notReceived" },\n'
)

text = PAGE.read_text(encoding="utf-8")
assert BEFORE in text, "the reason list is no longer written this way; this control does not apply"
# The already-applied guard is on the code-shaped form, not on the bare word: the screen's own
# docstring names the four invented codes as history, and a substring check reported the
# explanation as the defect it describes. The same mistake `preconditions-come-from-the-server`
# records — a check a prose mention can trip is one somebody satisfies by deleting the prose.
assert '{ code: "amount_mismatch"' not in text, "already applied"

PAGE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = PAGE.read_text(encoding="utf-8")
assert '"amount_mismatch"' in after and '"wrong_beneficiary"' in after, "THE EDIT DID NOT LAND"
print("control 4 applied: the screen offers two invented reason codes")
