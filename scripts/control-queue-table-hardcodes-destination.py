"""Control 4: the queue table decides for itself where a row opens.

The failure mode is not a broken link — it is **the wrong screen for the right row**. An
accountant clicking a bundle in the unresolved-bundles queue would land on an attempt screen
showing a real attempt with that id, or a 404 that reads as a stale link. The first is worse: they
would act on somebody else's work believing it was theirs.

Written as the shape somebody actually reaches for — every row is a link, because "why does this
queue not link anywhere?" is a reasonable question with an unreasonable answer.
"""

import pathlib

TABLE = pathlib.Path("apps/admin-web/components/queue-table.tsx")

BEFORE = """                    {listing.detail_path === null ? (
                      <BidiText>{row.reference}</BidiText>
                    ) : (
                      <Link href={`${listing.detail_path}/${row.id}`}>
                        <BidiText>{row.reference}</BidiText>
                      </Link>
                    )}"""

AFTER = """                    <Link href={`/payment-attempts/${row.id}`}>
                      <BidiText>{row.reference}</BidiText>
                    </Link>"""

text = TABLE.read_text(encoding="utf-8")
assert BEFORE in text, "the table no longer renders the link this way; this control does not apply"

TABLE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = TABLE.read_text(encoding="utf-8")
assert "listing.detail_path" not in after, "THE EDIT DID NOT LAND"
assert "/payment-attempts/${row.id}" in after, "THE EDIT DID NOT LAND"
print("control 4 applied: every queue row now links to the attempt screen")
