"""Control: the screen stops comparing the two new-password fields.

**The one piece of validation this screen owns**, and the reason it owns it: the server has no
second field to compare against, so a typo in a new password is accepted and the person is locked
out of the account they had just changed.

Nothing fails. The request succeeds, the response says `changed: true`, and the screen reports
success — the failure arrives at the next sign-in, by which time nobody remembers what they typed.

Modelled as the tidy-looking simplification: drop the check because "the server validates the
password anyway". It does; it validates the *new* one against the policy, which is a different
question from whether the person typed what they meant.
"""

import pathlib

BEFORE = """    if (next !== again) {
"""
AFTER = """    if (false) {
"""

for app in ("admin-web", "trader-pwa"):
    page = pathlib.Path("apps", app, "app", "password", "page.tsx")
    text = page.read_text(encoding="utf-8")
    assert BEFORE in text, f"{app}: the confirmation check is no longer written this way"
    page.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")
    assert "if (false) {" in page.read_text(encoding="utf-8"), f"{app}: THE EDIT DID NOT LAND"

print("control applied: neither screen compares the two new-password fields")
