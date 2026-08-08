"""The ownership schema, checked in the metadata — where the defect was visible.

M2 built `uq_trader_users_primary_contact` on `is_primary` where
`04_Database_Schema.md:360-362` specifies `trader_users(trader_id)`. The key column
did not exist, so the flag became the key, and the constraint enforced "one primary
trader contact in the entire database" instead of one per business.

The tests that catch that behaviourally live in `tests/integration` and need a
PostgreSQL server. This file exists because **they should never have been the only
ones**: the defect was a fact about `Base.metadata`, readable with no database, no
fixture and no migration run. A negative control confirmed the point — re-keying
the index to `is_primary` left the whole of `tests/backend` green, so on a laptop
with no database the reintroduced defect was invisible.

So the same properties are asserted twice, at two costs. Here, for free, on every
run. There, against a real server, where a predicate that parses can still fail to
bite. Neither subsumes the other: metadata cannot prove PostgreSQL accepts the
predicate, and a passing integration suite proves nothing on a machine that skips
it.

Covers: DB-OWN-001, DB-PRIMARY-001, DB-PRIMARY-003, DB-TRADER-001.
"""

from __future__ import annotations

import re

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
from app.db.base import Base
from app.db.models.identity import ACCOUNT_STATUSES

TRADER_USERS = Base.metadata.tables["trader_users"]
TRADERS = Base.metadata.tables["traders"]

# Doc 04 §6.3 and §7.1, as key facts rather than as prose. Each is a statement the
# specification makes that a model can silently stop honouring.
PRIMARY_CONTACT_INDEX = "uq_trader_users_one_primary"


def index_named(table: object, name: str) -> object | None:
    return next((index for index in table.indexes if index.name == name), None)


def test_the_primary_contact_index_is_keyed_on_the_trader() -> None:
    """The regression test for the defect, at metadata level.

    Keyed on `trader_id`, not on `is_primary`. A unique index on the flag with a
    `WHERE is_primary` predicate is a single-row table: it permits exactly one
    primary contact across all traders, which is not a narrower version of the rule
    doc 04 states — it is a different rule that happens to reject duplicates too,
    which is why the constraint test M2 shipped stayed green.
    """

    index = index_named(TRADER_USERS, PRIMARY_CONTACT_INDEX)

    assert index is not None, (
        f"{PRIMARY_CONTACT_INDEX} is absent. 04_Database_Schema.md:360-362 names it; "
        f"present instead: {sorted(i.name or '' for i in TRADER_USERS.indexes)}"
    )
    assert index.unique, f"{PRIMARY_CONTACT_INDEX} must be unique to constrain anything"
    assert [column.name for column in index.columns] == ["trader_id"], (
        f"{PRIMARY_CONTACT_INDEX} is keyed on "
        f"{[column.name for column in index.columns]}. Doc 04 keys it on trader_id: "
        "one primary contact per trader business. Keying it on is_primary enforces "
        "one primary contact in the entire database."
    )


def test_the_primary_contact_predicate_names_values_the_check_admits() -> None:
    """A predicate referencing an impossible value is a condition that never fires.

    The predicate excludes retired primaries so a replacement can be appointed. If
    it names a status no row may hold, the exclusion never applies and the index
    silently widens to every primary row. That coupling is why the value CHECK and
    this predicate had to change in the same migration.
    """

    index = index_named(TRADER_USERS, PRIMARY_CONTACT_INDEX)
    assert index is not None
    predicate = str(index.dialect_options["postgresql"]["where"])

    quoted = set(re.findall(r"'([a-z_]+)'", predicate))

    assert quoted, f"the predicate names no status value at all: {predicate!r}"
    assert quoted <= set(ACCOUNT_STATUSES), (
        f"the predicate of {PRIMARY_CONTACT_INDEX} names {sorted(quoted - set(ACCOUNT_STATUSES))}, "
        f"which ck_trader_users_status forbids. Admitted values: {sorted(ACCOUNT_STATUSES)}. "
        "A predicate that can never be false does not narrow the index."
    )


def test_trader_users_are_owned_by_a_trader() -> None:
    """`ActorContext.trader_id` has no other source."""

    column = TRADER_USERS.columns["trader_id"]

    assert not column.nullable, (
        "trader_users.trader_id is nullable, so a login can exist with no owning "
        "business and every ownership guard has a case with no answer"
    )
    targets = {foreign_key.target_fullname for foreign_key in column.foreign_keys}
    assert targets == {"traders.id"}, f"trader_id points at {targets or 'nothing'}"


def test_traders_has_no_combined_status_column() -> None:
    """DOC-CONFLICT-024's structural decision, made unrepresentable.

    The projection document 05 exposes is computed from three columns at read time.
    A stored fourth copy would drift from them, and the register records that the
    axes stay separate — so the column's absence is the decision, not an omission.
    """

    assert "status" not in TRADERS.columns, (
        "traders has acquired a combined `status` column. DOC-CONFLICT-024 records "
        "approval, operation and login-account state as three axes; a stored "
        "projection is a fourth copy of three facts."
    )


def test_traders_stores_no_balance() -> None:
    """`04_Database_Schema.md:469` prohibits it without a ledger, in those terms."""

    balance_like = sorted(column.name for column in TRADERS.columns if "balance" in column.name)

    assert balance_like == [], (
        f"traders carries {balance_like}. Doc 04:469 prohibits an authoritative "
        "current_balance_irr without a ledger and reconciliation model, and names a "
        "mutable cached balance without one as explicitly forbidden."
    )
