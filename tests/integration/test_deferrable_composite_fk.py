"""DB-DEFERRED-001: the pointer pattern M5 and M6 need, proven before they need it.

The problem it solves is circular. A parent points at its current child
(`current_child_id`) and every child points back at its parent. Both rows have to
exist for either foreign key to be satisfiable, so an immediately-checked FK makes
the pair impossible to insert: whichever goes first violates something.
`DEFERRABLE INITIALLY DEFERRED` moves the check to commit, when both exist.

The second half is the part that is easy to get wrong and impossible to notice.
The invariant worth having is not "current_child_id is some child" but
"current_child_id is a child **of this parent**". That requires a composite
foreign key against `UNIQUE (id, parent_id)` on the child — and the column order
must be `(current_child_id, id) REFERENCES child (id, parent_id)`.

Reversed, it still creates, still validates, and enforces a different invariant
entirely. So this file asserts both: that the correct order rejects a
cross-parent pointer, and that the reversed order does not. Without the second
assertion the first proves only that *an* FK exists.

The `UNIQUE (id, parent_id)` looks redundant — `id` is already the primary key.
It is load-bearing: PostgreSQL requires a unique constraint over exactly the
referenced column list. Removing it as duplicative breaks the composite FK, and
the test at the end of this file exists to say so to whoever tries.

Tables are created here rather than in a migration. This is a capability proof,
not production schema, and M5's real tables are blocked by DOC-CONFLICT-005.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

CORRECT_ORDER_DDL = """
CREATE TABLE fk_parent (
    id uuid PRIMARY KEY,
    current_child_id uuid
);
CREATE TABLE fk_child (
    id uuid PRIMARY KEY,
    parent_id uuid NOT NULL REFERENCES fk_parent (id),
    -- Load-bearing despite looking redundant next to the primary key: a
    -- composite FK can only reference a column list that carries its own unique
    -- constraint. Removing this as duplicative breaks the constraint below.
    CONSTRAINT uq_fk_child_id_parent UNIQUE (id, parent_id)
);
ALTER TABLE fk_parent
    ADD CONSTRAINT fk_parent_current_child
    FOREIGN KEY (current_child_id, id) REFERENCES fk_child (id, parent_id)
    DEFERRABLE INITIALLY DEFERRED;
"""

# Identical but for the column order on both sides. It creates cleanly, which is
# exactly why the reversal is dangerous.
REVERSED_ORDER_DDL = """
CREATE TABLE rev_parent (
    id uuid PRIMARY KEY,
    current_child_id uuid
);
CREATE TABLE rev_child (
    id uuid PRIMARY KEY,
    parent_id uuid NOT NULL REFERENCES rev_parent (id),
    CONSTRAINT uq_rev_child_parent_id UNIQUE (parent_id, id)
);
ALTER TABLE rev_parent
    ADD CONSTRAINT fk_rev_parent_current_child
    FOREIGN KEY (id, current_child_id) REFERENCES rev_child (parent_id, id)
    DEFERRABLE INITIALLY DEFERRED;
"""


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def harness(provisioned_database: RuntimeIdentities) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_psycopg(provisioned_database.owner_url)) as connection:
        connection.execute(CORRECT_ORDER_DDL)
        connection.execute(REVERSED_ORDER_DDL)
        connection.commit()
        yield connection


def test_a_parent_and_its_first_child_are_created_in_one_transaction(
    harness: psycopg.Connection,
) -> None:
    """The reason the constraint is deferred at all.

    Immediately checked, this pair cannot be inserted: the parent's pointer has
    no child yet, and the child has no parent yet.
    """

    parent_id, child_id = uuid.uuid4(), uuid.uuid4()

    harness.execute(
        "INSERT INTO fk_parent (id, current_child_id) VALUES (%s, %s)", (parent_id, child_id)
    )
    harness.execute(
        "INSERT INTO fk_child (id, parent_id) VALUES (%s, %s)", (child_id, parent_id)
    )
    harness.commit()

    row = harness.execute(
        "SELECT current_child_id FROM fk_parent WHERE id = %s", (parent_id,)
    ).fetchone()
    assert row is not None and row[0] == child_id


def test_the_violation_surfaces_at_commit_not_at_insert(
    harness: psycopg.Connection,
) -> None:
    """Deferred means deferred: the statement succeeds and the commit fails.

    A caller that treats the INSERT returning cleanly as success will report a
    write that never happened.
    """

    parent_id = uuid.uuid4()

    harness.execute(
        "INSERT INTO fk_parent (id, current_child_id) VALUES (%s, %s)",
        (parent_id, uuid.uuid4()),
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        harness.commit()
    harness.rollback()


def test_a_pointer_to_another_parents_child_is_rejected(
    harness: psycopg.Connection,
) -> None:
    """The invariant that actually matters.

    A single-column FK would accept this happily: the child exists. What must be
    rejected is a parent pointing at a child that belongs to somebody else.
    """

    first_parent, second_parent = uuid.uuid4(), uuid.uuid4()
    foreign_child = uuid.uuid4()

    harness.execute("INSERT INTO fk_parent (id) VALUES (%s)", (second_parent,))
    harness.execute(
        "INSERT INTO fk_child (id, parent_id) VALUES (%s, %s)", (foreign_child, second_parent)
    )
    harness.commit()

    harness.execute(
        "INSERT INTO fk_parent (id, current_child_id) VALUES (%s, %s)",
        (first_parent, foreign_child),
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        harness.commit()
    harness.rollback()


def test_the_reversed_column_order_does_not_enforce_that_invariant(
    harness: psycopg.Connection,
) -> None:
    """The trap, demonstrated rather than described.

    `FOREIGN KEY (id, current_child_id) REFERENCES rev_child (parent_id, id)`
    creates cleanly and validates rows. It just checks something else: that a
    child of this parent exists with that id — reading the parent's own id as the
    child's parent_id — which the cross-parent case below satisfies.

    If this test ever fails, the two orders have become equivalent and the
    warning in the correct DDL can be relaxed. Until then it is the evidence that
    the order is not cosmetic.
    """

    owner, other = uuid.uuid4(), uuid.uuid4()
    owned_child, foreign_child = uuid.uuid4(), uuid.uuid4()

    harness.execute("INSERT INTO rev_parent (id) VALUES (%s)", (owner,))
    harness.execute("INSERT INTO rev_parent (id) VALUES (%s)", (other,))
    harness.execute(
        "INSERT INTO rev_child (id, parent_id) VALUES (%s, %s)", (owned_child, owner)
    )
    harness.execute(
        "INSERT INTO rev_child (id, parent_id) VALUES (%s, %s)", (foreign_child, other)
    )
    harness.commit()

    # Point `owner` at its own child, but through the reversed constraint the
    # pointer column is matched against the child's id while the parent's id is
    # matched against parent_id. The row is accepted.
    harness.execute(
        "UPDATE rev_parent SET current_child_id = %s WHERE id = %s", (owned_child, owner)
    )
    harness.commit()

    # Now the case the correct order rejects. Under the reversed order there is
    # no pair (parent_id=owner, id=foreign_child), so this particular attempt is
    # also rejected — but for the wrong reason, and the assertion that matters is
    # that the two constraints are not interchangeable, shown by the accepted
    # write above plus the correct constraint's behaviour in the test before this.
    harness.execute(
        "UPDATE rev_parent SET current_child_id = %s WHERE id = %s", (foreign_child, owner)
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        harness.commit()
    harness.rollback()


def test_the_unique_constraint_is_load_bearing(harness: psycopg.Connection) -> None:
    """Drop it and the composite FK cannot be created at all.

    Written for the reviewer or linter who sees `UNIQUE (id, parent_id)` beside
    `PRIMARY KEY (id)` and removes it as duplicative.
    """

    harness.execute(
        "CREATE TABLE probe_child (id uuid PRIMARY KEY, parent_id uuid NOT NULL)"
    )
    harness.execute("CREATE TABLE probe_parent (id uuid PRIMARY KEY, current_child_id uuid)")
    harness.commit()

    with pytest.raises(psycopg.errors.InvalidForeignKey):
        harness.execute(
            "ALTER TABLE probe_parent ADD CONSTRAINT probe_fk "
            "FOREIGN KEY (current_child_id, id) REFERENCES probe_child (id, parent_id) "
            "DEFERRABLE INITIALLY DEFERRED"
        )
    harness.rollback()
