"""Control 4: an unconfirmed claim renders as zero.

`confirmed_amount_irr` is `null` until somebody agrees. **Zero is an agreement** — and on this
screen the difference decides whether the accountant still has work to do, so a claim showing `0`
reads as reviewed and settled at nothing.

Worse here than on the order list, where the same idiom only misreports a price. Here it hides a
payment nobody has confirmed.
"""

import pathlib

PAGE = pathlib.Path("apps/admin-web/app/incoming-payments/[receiptId]/page.tsx")

BEFORE = """                  {phase.receipt.confirmed_amount_irr === null ? (
                    <span>{t("receipt.notConfirmedYet")}</span>
                  ) : (
                    <BidiText>{phase.receipt.confirmed_amount_irr}</BidiText>
                  )}"""

AFTER = """                  <BidiText>{phase.receipt.confirmed_amount_irr ?? 0}</BidiText>"""

text = PAGE.read_text(encoding="utf-8")
assert BEFORE in text, "the unconfirmed branch is no longer written this way"

PAGE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = PAGE.read_text(encoding="utf-8")
assert "confirmed_amount_irr ?? 0" in after, "THE EDIT DID NOT LAND"
print("control 4 applied: an unconfirmed claim renders as zero")
