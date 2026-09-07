"""Control 2: a recorded entry loses its reason.

A row with no sentence is an allowlist row. The list stops being an answer to "how much of this
system can a person actually use" and becomes a place things go to be excused — which is the
failure mode every recorded-gap list in this repository is written against.

`change-password` is chosen because its reason is the most easily deleted: "no slice has owned a
settings surface" reads like an apology rather than a fact, and somebody tidying would.
"""

import pathlib
import re

GATE = pathlib.Path("tests/backend/test_every_operation_has_a_screen.py")

text = GATE.read_text(encoding="utf-8")
key = '("POST", "/api/v1/auth/change-password"): ('
assert key in text, "the change-password entry is no longer written this way"

start = text.index(key)
end = text.index("),\n", start) + len("),\n")
replacement = '    ("POST", "/api/v1/auth/change-password"): "todo",\n'
GATE.write_text(text[:start - 4] + replacement + text[end:], encoding="utf-8")

after = GATE.read_text(encoding="utf-8")
assert '"/api/v1/auth/change-password"): "todo"' in after, "THE EDIT DID NOT LAND"
print("control 2 applied: an entry now has no reason")
