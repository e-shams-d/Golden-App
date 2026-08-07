"""No unique index may make a beneficiary IBAN or name one-per-row. Ever.

This is a forward-looking guard. `beneficiaries` and `trader_bank_accounts` arrive in
M5; the prohibition is written now because the constraint it forbids is the one a
reasonable person adds without thinking. "Two rows with the same IBAN must be a
mistake" is wrong here: the same person legitimately holds two accounts, two people
legitimately share a name, and the approved behaviour is that the service **warns**
rather than auto-merging. A unique index turns that warning into a refusal at data
entry, and the trader whose second account cannot be registered has no way around it.

The one permitted exception is `bank_accounts.normalized_iban` — centre-owned
accounts, where two rows for one IBAN really is a duplicate of the centre's own
record.

The asymmetry across the three tables is a recorded decision, not an accident:

  - `bank_accounts.normalized_iban` — nullable, null-tolerant regex, unique. A centre
    account may be registered before its IBAN is known.
  - `beneficiaries` (M5) — NOT NULL with the same regex, **not** unique. A payment
    destination without an IBAN cannot be paid, but duplicates are legitimate.
  - `trader_bank_accounts` — doc 04 specifies neither, and it must not be harmonised
    by assumption.

Copying the beneficiaries' NOT NULL form onto `bank_accounts` breaks legitimate null
IBANs; copying `bank_accounts`' unique onto beneficiaries breaks legitimate duplicate
entry. Both mistakes look like consistency.
"""

from __future__ import annotations

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
from app.db.base import Base
from app.db.models.bank import IBAN_UNIQUE_IS_PERMITTED_ONLY_ON

# Columns that identify a person or an account holder. A unique over any of these,
# outside the permitted pair, refuses data a human is entitled to enter twice.
IDENTITY_COLUMNS = frozenset({"iban", "normalized_iban", "account_number", "deposit_number"})


def unique_column_sets() -> list[tuple[str, tuple[str, ...]]]:
    """Every unique constraint and unique index, as (table, ordered columns).

    Both kinds, because a `UniqueConstraint` and an `Index(unique=True)` are
    interchangeable in effect and a prohibition that covered only one would be
    satisfied by using the other.
    """

    found: list[tuple[str, tuple[str, ...]]] = []
    for table_name, table in sorted(Base.metadata.tables.items()):
        for constraint in table.constraints:
            if constraint.__class__.__name__ == "UniqueConstraint":
                found.append((table_name, tuple(c.name for c in constraint.columns)))
        for index in table.indexes:
            if index.unique:
                found.append((table_name, tuple(c.name for c in index.columns)))
        # A column declared `unique=True` becomes a constraint above, so it is
        # already covered; asserted by the self-check test below.
    return found


def test_the_only_permitted_iban_unique_is_the_centre_account_one() -> None:
    offenders = [
        f"{table}({', '.join(columns)})"
        for table, columns in unique_column_sets()
        if len(columns) == 1
        and columns[0] in IDENTITY_COLUMNS
        and (table, columns[0]) not in IBAN_UNIQUE_IS_PERMITTED_ONLY_ON
    ]

    assert offenders == [], (
        "a unique constraint makes an account identifier one-per-row:\n"
        + "\n".join(offenders)
        + "\nDuplicates are legitimate and the approved behaviour is to warn, not "
        "to refuse. Only bank_accounts.normalized_iban may be unique."
    )


def test_no_unique_pairs_a_name_with_an_account_identifier() -> None:
    """The composite form of the same mistake, and the more tempting one.

    `UNIQUE(full_name, iban)` reads as harmless — surely the same person with the
    same IBAN is one row — and it refuses a legitimate correction where a trader
    re-registers a beneficiary after a typo in an earlier field.
    """

    offenders = [
        f"{table}({', '.join(columns)})"
        for table, columns in unique_column_sets()
        if len(columns) > 1
        and any(column in IDENTITY_COLUMNS for column in columns)
        and any("name" in column for column in columns)
    ]

    assert offenders == [], "a unique pairs a name with an account identifier:\n" + "\n".join(
        offenders
    )


def test_the_guard_sees_the_constraint_it_permits() -> None:
    """Guard the guard.

    Every assertion above passes trivially if `unique_column_sets()` returns
    nothing — which is exactly what a wrong reflection helper would do. So confirm
    it finds the one unique that is supposed to exist.
    """

    assert ("bank_accounts", ("normalized_iban",)) in unique_column_sets()


def test_the_guard_sees_composite_uniques_too() -> None:
    """The composite check is worthless if the helper only reports single columns."""

    composites = [columns for _table, columns in unique_column_sets() if len(columns) > 1]

    assert ("bank_profile_id", "version_number") in composites
