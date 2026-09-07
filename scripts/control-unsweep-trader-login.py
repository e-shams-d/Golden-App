"""Control 5: the trader login screen leaves the accessibility sweep.

Silent by construction — the page still renders, every functional test still passes, and nothing
checks it for accessibility again. That is precisely the state slice 3 found `/login`, `/evidence`
and `/offline` in, and the reason it was invisible is that `TRACE-SCREENS-001`'s
sweep-versus-routes comparison had only ever been written for `admin-web`.

`/login` is the target because it is the screen every trader must use before any other: if one
page's accessibility must be checked, it is that one.
"""

import pathlib

SWEEP = pathlib.Path("apps/trader-pwa/tests/a11y/shell.spec.ts")

BEFORE = '  "/login",\n'

text = SWEEP.read_text(encoding="utf-8")
assert BEFORE in text, "the login route is not swept; this control does not apply"

SWEEP.write_text(text.replace(BEFORE, "", 1), encoding="utf-8")

after = SWEEP.read_text(encoding="utf-8")
assert '"/login"' not in after, "THE EDIT DID NOT LAND"
print("control 5 applied: the trader login screen is no longer swept")
