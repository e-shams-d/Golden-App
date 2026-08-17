"""Two absences in the beneficiary surface, asserted rather than described.

M5 slice 2. Both of these are claims that something **does not exist**, which is
why neither can be proved by calling anything: a runtime denial shows a mechanism
that refused, and the claim here is that there is no mechanism to refuse with.

`06_Workflows_and_State_Machines.md:298` — "Amount is not beneficiary data" — and
DOC-CONFLICT-011's interim rule of strict trader-owned isolation. A disabled
sharing flag would satisfy every behavioural test and still be a flag somebody
turns on.

Covers: SVC-BEN-003, SEC-BEN-002.
"""

from __future__ import annotations

import ast
from pathlib import Path

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
from app.db.base import Base

APP_ROOT = Path(__file__).resolve().parents[2] / "services" / "backend" / "app"

# Words that would name money on a beneficiary. `amount` and `irr` are the obvious
# two; `balance`, `credit` and `limit` are here because `traders` already carries
# `credit_limit_irr` and the reflex that put it there would put one here too.
MONEY_WORDS = ("amount", "irr", "balance", "credit", "limit", "price", "value", "toman")

# Words that would name a second owner. `shared`, `share` and `visible` cover a
# flag; `traders` plural covers a join table's column.
SHARING_WORDS = ("shared", "share", "visible_to", "delegat", "traders")


def test_a_beneficiary_carries_no_amount_of_any_kind() -> None:
    """SVC-BEN-003.

    `15_Agent_Implementation_Plan.md:751`: "beneficiary never stores the payment
    amount." Asserted by scanning the mapped columns for money-shaped names rather
    than by comparing against a fixed column list, because a fixed list is what
    slice 1's `test_the_columns_match_document_04` already does — this one has to
    keep answering after a column is legitimately added.
    """

    table = Base.metadata.tables["beneficiaries"]
    offenders = sorted(
        column.name
        for column in table.columns
        if any(word in column.name.lower() for word in MONEY_WORDS)
    )

    assert offenders == [], (
        f"these beneficiary columns look like money: {offenders}. "
        "06_Workflows_and_State_Machines.md:298 says amount is not beneficiary data — "
        "it belongs to the payment request, and a beneficiary that carried one would "
        "let two requests to the same person disagree about what was owed."
    )


def test_no_column_could_give_a_beneficiary_a_second_owner() -> None:
    """SEC-BEN-002, the schema half.

    One `trader_id` and nothing else through which a second owner is expressible.
    Slice 1 asserts the single foreign key; this asserts that no *other* column has
    since arrived that could carry a sharing relationship.
    """

    table = Base.metadata.tables["beneficiaries"]
    offenders = sorted(
        column.name
        for column in table.columns
        if any(word in column.name.lower() for word in SHARING_WORDS)
    )

    assert offenders == [], f"these columns could name a second owner: {offenders}"


def test_no_table_joins_beneficiaries_to_more_than_one_trader() -> None:
    """SEC-BEN-002, the other place a sharing mechanism could live.

    A column on `beneficiaries` is one shape; a join table is the other, and it
    would not show up in the column scan at all. Any table carrying both a
    beneficiary reference and a trader reference, other than the payment tables
    that legitimately reference both, would be that mechanism.
    """

    offenders: list[str] = []
    for name, table in sorted(Base.metadata.tables.items()):
        if name == "beneficiaries":
            continue
        columns = {column.name for column in table.columns}
        if any("beneficiary" in column for column in columns) and "trader_id" in columns:
            offenders.append(name)

    assert offenders == [], (
        f"these tables join a beneficiary to a trader: {offenders}. If one of them is "
        "a payment request — which legitimately references both — this test needs the "
        "exception written down with its reason, not removed."
    )


def test_no_command_or_route_offers_cross_trader_reuse() -> None:
    """SEC-BEN-002, the code half, and the one that would still be needed if the
    schema were perfect.

    DOC-CONFLICT-011's rule is that the mechanism does not exist. A route that took
    a `trader_id` and reassigned a beneficiary, or a command parameter named for
    sharing, would be that mechanism even with no column behind it — it would fail
    at the database, which is a refusal rather than an absence.

    Scanned over the two modules the slice owns. A wider scan would match the
    payment tables' legitimate references in later slices and would have to be
    narrowed by exceptions, and an exception list is where this kind of check goes
    to die.
    """

    offenders: list[str] = []
    for relative in ("commands/beneficiary.py", "api/v1/beneficiaries.py"):
        tree = ast.parse((APP_ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.arg) and _is_sharing(node.arg):
                offenders.append(f"{relative}: parameter {node.arg}")
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and _is_sharing(node.target.id)
            ):
                offenders.append(f"{relative}: field {node.target.id}")

    assert offenders == [], (
        f"these names would let one beneficiary reach two traders: {offenders}"
    )


def _is_sharing(name: str) -> bool:
    lowered = name.lower()
    if lowered in {"trader_id", "beneficiary_id"}:
        return False
    return any(word in lowered for word in SHARING_WORDS)
