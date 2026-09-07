"""Control 3: the publication-correction grant is assigned to a role.

**The control that matters most in this slice, because what it tests is an absence.**

The correction screen was not built for one reason: `payment_publication.correct` is granted to no
role, POL-002 having deferred the preparer/approver split to an unresolved decision. That is a
deferral with an expiry date, and the expiry is invisible — the day somebody settles the decision
and assigns the grant, the centre gains a capability with no screen for it and nothing in the suite
would say so.

So the sabotage is the *good* event: the grant gets assigned. The gate must notice, because
noticing is the only thing that turns "not built yet" into something other than "forgotten".
"""

import pathlib
import re

CATALOGUE = pathlib.Path("docs/governance/permission_catalog.yaml")

text = CATALOGUE.read_text(encoding="utf-8")

entry = re.search(r"(^ {6}payment_publication\.correct:\n(?:[ ]{8}.*\n)*)", text, re.M)
assert entry is not None, "the correction permission is not in the catalogue"
block = entry.group(1)
assert "default_roles: []" in block, f"the grant is no longer unassigned:\n{block}"

CATALOGUE.write_text(
    text.replace(block, block.replace("default_roles: []", "default_roles: [manager]", 1), 1),
    encoding="utf-8",
)

after = CATALOGUE.read_text(encoding="utf-8")
found = re.search(r"^ {6}payment_publication\.correct:\n(?:[ ]{8}.*\n)*", after, re.M)
assert found and "default_roles: [manager]" in found.group(0), "THE EDIT DID NOT LAND"
print("control 3 applied: payment_publication.correct is now granted to manager")
