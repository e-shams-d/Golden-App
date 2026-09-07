"""Control 3: the client learns to page by offset.

§19.3 asks for a cursor. An offset re-reads from the top on every page, so rows shift under
somebody draining a queue and items are skipped or seen twice — in the one place whose whole
purpose is to touch every row exactly once.

The server ignores an unknown parameter, so this sabotage produces **no visible failure at all**:
the second page would simply be the first page again, and a person working the queue would see
duplicates without any error to report. That is precisely why the claim is checked structurally
rather than by observing behaviour.
"""

import pathlib

MODULE = pathlib.Path("apps/admin-web/src/queues.ts")

BEFORE = '  if (query.cursor) parameters.set("cursor", query.cursor);\n'
AFTER = (
    '  if (query.cursor) parameters.set("cursor", query.cursor);\n'
    '  if (query.offset !== undefined) parameters.set("offset", String(query.offset));\n'
)

TYPE_BEFORE = "  cursor?: string | null;\n"
TYPE_AFTER = "  cursor?: string | null;\n  offset?: number;\n"

text = MODULE.read_text(encoding="utf-8")
assert BEFORE in text, "the cursor line is no longer written this way"
assert TYPE_BEFORE in text, "the query type is no longer written this way"

updated = text.replace(BEFORE, AFTER, 1).replace(TYPE_BEFORE, TYPE_AFTER, 1)
MODULE.write_text(updated, encoding="utf-8")

after = MODULE.read_text(encoding="utf-8")
assert 'parameters.set("offset"' in after, "THE EDIT DID NOT LAND"
assert "offset?: number;" in after, "THE EDIT DID NOT LAND"
print("control 3 applied: the client can now construct an offset")
