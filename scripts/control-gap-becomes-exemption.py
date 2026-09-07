"""Control 2: a recorded gap is quietly promoted to an exemption.

**The control that matters in this slice**, because it is the gate defeating itself rather than
the code defeating the gate.

`EXEMPT` and `RECORDED_GAPS` mean opposite things. An exemption says "the precondition is about a
different aggregate, and here is the read that issues it" — a design. A gap says "there is nowhere
to get this" — the defect. Moving an entry from the second to the first turns a defect into a
design with one line, no code change, and nothing to review but a sentence.

That is exactly how a recorded gap becomes a place things go to be forgotten, and it is why the
file carries `test_no_recorded_gap_has_quietly_been_closed` and
`test_the_two_kinds_of_entry_are_not_conflated`. This asks whether either of them bites.

The receipt confirm is the one moved, because it is the entry slice 6 has promised to close: if a
promise can be discharged by relabelling it, the promise was never worth writing down.
"""

import pathlib

GATE = pathlib.Path("tests/backend/test_preconditions_have_a_source.py")

GAP_KEY = '    ("POST", "/api/v1/incoming-payment-receipts/{receipt_id}/confirm"): ('
EXEMPT_ANCHOR = '    ("PUT", "/api/v1/roles/{role_id}/permissions"): ('

text = GATE.read_text(encoding="utf-8")
assert GAP_KEY in text, "the receipt confirm is no longer recorded as a gap"
assert EXEMPT_ANCHOR in text, "the exemptions are no longer written this way"

# Remove the gap entry, whatever its wording, and add an exemption in its place.
start = text.index(GAP_KEY)
end = text.index("),\n", start) + len("),\n")
text = text[:start] + text[end:]

# A **well-formed** exemption, and that matters: the first version of this control wrote a bare
# string where the dict holds `(read_path, reason)`, so the gate caught it by failing to unpack
# rather than by checking anything. A sabotage that trips on a type error has not tested the
# property — it has tested Python. This writes exactly what a careless person would write: the
# right shape, a plausible sentence, and a read path that does not exist.
promoted = (
    '    ("POST", "/api/v1/incoming-payment-receipts/{receipt_id}/confirm"): (\n'
    '        "/{receipt_id}",\n'
    '        "the version is the receipt\'s and the aggregate read issues it, so this command is "\n'
    '        "not orphaned after all"\n'
    "    ),\n"
)
text = text.replace(EXEMPT_ANCHOR, promoted + EXEMPT_ANCHOR, 1)

GATE.write_text(text, encoding="utf-8")

after = GATE.read_text(encoding="utf-8")
assert after.count('/api/v1/incoming-payment-receipts/{receipt_id}/confirm') == 1, (
    "THE EDIT DID NOT LAND — the entry should appear exactly once, now as an exemption"
)
assert "the aggregate read" in after, "THE EDIT DID NOT LAND"
print("control 2 applied: a recorded gap is now an exemption")
