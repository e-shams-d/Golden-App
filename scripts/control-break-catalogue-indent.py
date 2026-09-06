"""Control 3: make the catalogue unparseable to the new check.

Guard the guard. `test_nothing_in_the_catalogue_could_have_gated_the_notifications_item` concludes
"no notification permission exists" from a regex over six-space-indented codes. A pattern that
stopped matching would reach the same conclusion for the wrong reason, and control 1 would go
quiet along with it.

Re-indenting every permission code by two spaces is the cheapest way to produce that state without
changing which permissions the catalogue actually defines.
"""

import pathlib
import re

CATALOGUE = pathlib.Path("docs/governance/permission_catalog.yaml")

CODE = re.compile(r"^ {6}([a-z_]+\.[a-z_]+):", re.M)

text = CATALOGUE.read_text(encoding="utf-8")
before = len(CODE.findall(text))
assert before > 100, f"only {before} codes matched before the edit; control is already vacuous"

CATALOGUE.write_text(CODE.sub(r"        \1:", text), encoding="utf-8")

after = len(CODE.findall(CATALOGUE.read_text(encoding="utf-8")))
assert after == 0, f"THE EDIT DID NOT LAND — {after} codes still match"
print(f"control 3 applied: {before} parseable codes became {after}")
