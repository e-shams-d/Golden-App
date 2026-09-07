"""Control 5: one queue loses its Persian label.

**Silent by construction.** `queueLabel` falls back to the URL segment, so the screen keeps
working and shows `blocked-dispatches` to a Persian reader. No request fails, no test that renders
the page notices, and the defect is discovered by somebody reading a card.

That is the whole reason the label check reads `BUILT` from the backend: a missing thing is silent
in a way a wrong thing is not.
"""

import pathlib

MESSAGES = pathlib.Path("packages/localization/src/messages.ts")

BEFORE = '  "queue.blocked-dispatches": "تحویل‌های متوقف‌شده",\n'

text = MESSAGES.read_text(encoding="utf-8")
assert BEFORE in text, "the label is no longer written this way; this control does not apply"

MESSAGES.write_text(text.replace(BEFORE, "", 1), encoding="utf-8")

after = MESSAGES.read_text(encoding="utf-8")
assert '"queue.blocked-dispatches"' not in after, "THE EDIT DID NOT LAND"
print("control 5 applied: blocked-dispatches has no Persian label")
