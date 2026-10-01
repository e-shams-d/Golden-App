"""The approved weight units, written in two languages, compared.

`db/models/gold_sale.py` holds the list the database CHECK enforces, and the comment above
it records that an early draft invented `KILOGRAM` and omitted `MITHQAL` — the measure gold
is actually quoted in here. That draft was found and corrected in Python.

The trader's order form carried its own copy and kept the draft, so for as long as both
existed the form offered a unit the server refuses and withheld the one most of this market
trades in. Nothing compared them, because nothing had to: each file was internally
consistent and the contract types the field as a plain string, so neither OpenAPI nor
TypeScript could notice.

Read as text rather than imported: the TypeScript is not importable from pytest, and a test
that only checked the Python half would pass against exactly the state this is written for.

Covers: the second half of a fix that landed in one language.
"""

from __future__ import annotations

import pathlib
import re

from app.db.models.gold_sale import WEIGHT_UNITS

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
TRADER_FORM = REPOSITORY_ROOT / "apps/trader-pwa/app/gold-orders/page.tsx"
DECLARATION = re.compile(r"const UNITS = \[(?P<items>[^\]]*)\] as const;")


def _units_in_the_form() -> tuple[str, ...]:
    source = TRADER_FORM.read_text(encoding="utf-8")
    match = DECLARATION.search(source)
    assert match is not None, (
        f"no `const UNITS = [...] as const;` in {TRADER_FORM.relative_to(REPOSITORY_ROOT)}. "
        "If the declaration moved, move this test with it rather than deleting it — the "
        "list still exists in two languages and still has to agree."
    )
    return tuple(re.findall(r'"([^"]+)"', match.group("items")))


def test_the_form_offers_exactly_the_units_the_server_approves() -> None:
    """Equality, not containment, and each direction fails for its own reason."""

    offered = _units_in_the_form()
    approved = tuple(WEIGHT_UNITS)

    refused = [unit for unit in offered if unit not in approved]
    assert not refused, (
        f"the order form offers {refused}, which the server refuses with "
        f"BUSINESS_RULE_VIOLATION. A trader who picks one fills in the whole form and is "
        f"told the unit is not approved. The server's list is {list(approved)}."
    )

    missing = [unit for unit in approved if unit not in offered]
    assert not missing, (
        f"the server approves {missing} and the form does not offer it. This is the half "
        f"that costs an order rather than an error message: MITHQAL is the measure gold is "
        f"quoted in here, and a trader who works in it cannot enter one at all."
    )

    assert offered == approved, (
        f"the two lists hold the same units in a different order: form={list(offered)}, "
        f"server={list(approved)}. Order is what a person sees first; keep them identical."
    )
