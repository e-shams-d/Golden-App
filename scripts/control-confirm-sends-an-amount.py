"""Control 5: a confirmation body carries an amount.

§17 `:1131`'s "amount is exact" is honoured by the field's **absence** from the request models —
`SVC-CONFIRM-003` asserts the absence rather than testing a value, and the reason is that the
attempt already knows what was sent. A client figure could disagree with the row, and then the
server has two answers to one question about money that has moved.

`extra="forbid"` means the server would answer 422, so this is not a silent defect at runtime. It
is a silent defect in *review*: the field looks helpful, the shape looks symmetrical with the
retry's, and the screen sending it would pass every gate that does not read the body.
"""

import pathlib

MODULE = pathlib.Path("apps/admin-web/src/payment-results.ts")

BEFORE = """      bank_tracking_number: input.bankTrackingNumber,
      bank_result_at: input.bankResultAt,"""

AFTER = """      bank_tracking_number: input.bankTrackingNumber,
      bank_result_at: input.bankResultAt,
      amount_irr: 0,"""

text = MODULE.read_text(encoding="utf-8")
assert BEFORE in text, "the confirm-paid body is no longer written this way"
assert "amount_irr: 0" not in text, "already applied"

MODULE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = MODULE.read_text(encoding="utf-8")
assert "amount_irr: 0," in after, "THE EDIT DID NOT LAND"
print("control 5 applied: confirm-paid now sends an amount")
