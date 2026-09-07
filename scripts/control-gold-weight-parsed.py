"""Control 4: a gold weight is parsed to a number before it is sent.

`gold_weight` is a string in the contract for the reason `MONEY_TIME_CONTRACT` rule 8 gives for
amounts: a weight in grams to three decimal places is not safe as a JSON number.

**Silent by construction.** `Number("12.345")` is `12.345` and looks right; the failure is in the
digit nobody checks, on the order where it matters, months later. The contract accepts a number as
well as a string, so the server takes it without complaint.
"""

import pathlib

PAGE = pathlib.Path("apps/trader-pwa/app/gold-orders/page.tsx")

BEFORE = "        goldWeight: weight,\n"
AFTER = "        goldWeight: String(Number(weight)),\n"

text = PAGE.read_text(encoding="utf-8")
assert BEFORE in text, "the weight is no longer passed through this way"

PAGE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = PAGE.read_text(encoding="utf-8")
assert "String(Number(weight))" in after, "THE EDIT DID NOT LAND"
print("control 4 applied: the weight round-trips through a JavaScript number")
