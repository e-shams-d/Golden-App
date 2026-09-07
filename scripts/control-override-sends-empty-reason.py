"""Control 1: the screen sends an empty override reason instead of omitting it.

**The only control on these screens that changes what the system allows.** Without a reason the
server refuses to dispatch against an order that is not fully paid; with one the refusal becomes a
recorded override, with `guard_override_at` and the reason kept for review.

An empty string is a reason nobody wrote, recorded as though somebody had. The dispatch succeeds,
the audit trail says an override was authorised, and **nothing about the request looks wrong** —
which is why this is the sabotage worth running rather than the one worth describing.

Written as the idiom that produces it by accident: drop the `|| null`, because "the field is
optional anyway".
"""

import pathlib

PAGE = pathlib.Path("apps/admin-web/app/gold-orders/[orderId]/page.tsx")

BEFORE = "                      guardOverrideReason: overrideReason.trim() || null,\n"
AFTER = "                      guardOverrideReason: overrideReason.trim(),\n"

text = PAGE.read_text(encoding="utf-8")
assert BEFORE in text, "the override is no longer passed this way; this control does not apply"

PAGE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = PAGE.read_text(encoding="utf-8")
assert "guardOverrideReason: overrideReason.trim()," in after, "THE EDIT DID NOT LAND"
assert "overrideReason.trim() || null" not in after, "THE EDIT DID NOT LAND"
print("control 1 applied: an empty override reason is now sent")
