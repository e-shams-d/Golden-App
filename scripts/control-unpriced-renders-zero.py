"""Control 5: an unpriced order renders as zero.

`expected_amount_irr` is `null` until the centre prices the order. **Zero is a price.** Rendering
it tells a trader the centre has quoted them nothing — a different and much worse claim than "not
yet priced", and the one they would act on.

Written as the idiom that produces it by accident: `?? 0`, which reads as defensive and is a
falsehood about money.
"""

import pathlib

PAGE = pathlib.Path("apps/trader-pwa/app/gold-orders/page.tsx")

BEFORE = """                        {order.expected_amount_irr === null ? (
                          <span>{t("gold.notPricedYet")}</span>
                        ) : (
                          <BidiText>{order.expected_amount_irr}</BidiText>
                        )}"""

AFTER = """                        <BidiText>{order.expected_amount_irr ?? 0}</BidiText>"""

text = PAGE.read_text(encoding="utf-8")
assert BEFORE in text, "the unpriced branch is no longer written this way"

PAGE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = PAGE.read_text(encoding="utf-8")
assert "expected_amount_irr ?? 0" in after, "THE EDIT DID NOT LAND"
print("control 5 applied: an unpriced order renders as zero")
