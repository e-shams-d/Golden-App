"""Control 1: approve a notification permission.

The exemption granted to `/notifications` rests entirely on there being nothing to gate it on.
This adds something, in the catalogue's own shape, and asserts the edit landed before the suite
runs — a replacement that silently did not apply looks exactly like a gap in the tests.
"""

import pathlib

CATALOGUE = pathlib.Path("docs/governance/permission_catalog.yaml")

ANCHOR = "      audit.read:\n"
ADDED = (
    "      notification.read:\n"
    "        default_roles: [accountant, manager, business_admin]\n"
    "        constraints: [authenticated_active]\n"
)

text = CATALOGUE.read_text(encoding="utf-8")
assert ANCHOR in text, "the anchor entry is gone; this control no longer applies"
assert "notification.read" not in text, "the catalogue already defines it — control is vacuous"

CATALOGUE.write_text(text.replace(ANCHOR, ADDED + ANCHOR, 1), encoding="utf-8")

after = CATALOGUE.read_text(encoding="utf-8")
assert "      notification.read:\n" in after, "THE EDIT DID NOT LAND"
print("control 1 applied: notification.read is now in the catalogue")
