"""Control 3: the pricing screen calculates the expected amount itself.

Two answers to one question about money. The server derives `expected_amount_irr` from the weight
and the unit price; a screen that also derives it agrees today and disagrees the first time
rounding changes — and the figure a trader was quoted then depends on which surface they happened
to read.

Written as the helpful-looking version: show the accountant what the total will be *before* they
submit. That is a reasonable thing to want and the wrong way to get it — the honest version asks
the server, which is what the preview pattern does elsewhere in this application.
"""

import pathlib

PAGE = pathlib.Path("apps/admin-web/app/gold-orders/[orderId]/page.tsx")

BEFORE = '                  required\n                  value={unitPrice}\n                />\n'
AFTER = (
    "                  required\n"
    "                  value={unitPrice}\n"
    "                />\n"
    "                <span className=\"text-xs\">\n"
    "                  {Number(unitPrice) * Number(phase.order.gold_weight)}\n"
    "                </span>\n"
)

text = PAGE.read_text(encoding="utf-8")
assert BEFORE in text, "the unit price input is no longer written this way"

PAGE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = PAGE.read_text(encoding="utf-8")
assert "Number(unitPrice) * Number(" in after, "THE EDIT DID NOT LAND"
print("control 3 applied: the pricing screen computes its own total")
