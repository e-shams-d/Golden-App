"""Control 1: the reject echoes the receipt's version instead of the match's.

**This is slice 5's mistaken belief made real**, which is why it leads the slice.

That gate recorded both incoming-payment gaps as needing the receipt's version. Only `confirm`
does; `reject` passes `incoming_payment_match_id` and edits the match row. A screen built on the
recorded belief sends a header that is present, well-formed, and about a different row — the
server refuses it, but only after somebody made the decision, and the refusal reads as a
concurrency problem rather than a mistake in the client.

Written as the tempting version: the page already holds the receipt's `ifMatch`, so reusing it
saves a request. That saving is the whole defect.
"""

import pathlib

PAGE = pathlib.Path("apps/admin-web/app/incoming-payments/[receiptId]/page.tsx")

BEFORE = """                                  const { ifMatch } = await readMatch(receiptId, match.id);
                                  await rejectMatch(
                                    receiptId,
                                    match.id,
                                    ifMatch,
                                    rejectionReason,
                                  );"""

AFTER = """                                  await rejectMatch(
                                    receiptId,
                                    match.id,
                                    phase.ifMatch,
                                    rejectionReason,
                                  );"""

text = PAGE.read_text(encoding="utf-8")
assert BEFORE in text, "the reject handler is no longer written this way"

PAGE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = PAGE.read_text(encoding="utf-8")
assert "readMatch(receiptId" not in after, "THE EDIT DID NOT LAND"
assert "match.id,\n                                    phase.ifMatch," in after, "DID NOT LAND"
print("control 1 applied: reject now echoes the receipt's version")
