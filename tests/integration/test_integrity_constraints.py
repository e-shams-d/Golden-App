"""Each constraint must actually reject what it claims to.

A CHECK that exists but does not bite is worse than no CHECK: the schema review
sees it, the reader trusts it, and the bad row is written anyway. So every
assertion here inserts a row the constraint is supposed to refuse, and requires
the refusal to name that specific constraint. Naming matters — a row can be
rejected by NOT NULL or by a different CHECK entirely and the test would pass
while the constraint under test did nothing.

Insertions use raw SQL rather than the ORM on purpose. The database is the last
line, and it has to hold against a statement the application layer never
composed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest

pytestmark = pytest.mark.integration

ACTOR = uuid.uuid4()

AUDIT_COLUMNS = "action, outcome, actor_type, actor_id, metadata_schema, metadata_version"
AUDIT_VALUES = "%(action)s, %(outcome)s, %(actor_type)s, %(actor_id)s, %(schema)s, %(version)s"

AUDIT_DEFAULTS: dict[str, object] = {
    "action": "center_profile.renamed",
    "outcome": "success",
    "actor_type": "admin_user",
    "actor_id": ACTOR,
    "schema": "audit.center_profile",
    "version": 1,
}


def insert_audit(connection: psycopg.Connection, **overrides: object) -> None:
    values = {**AUDIT_DEFAULTS, **overrides}
    connection.execute(
        f"INSERT INTO audit_logs ({AUDIT_COLUMNS}) VALUES ({AUDIT_VALUES})", values
    )


@contextmanager
def rejected_by(constraint: str) -> Iterator[None]:
    """Require the statement to fail, and to fail on `constraint` specifically."""

    with pytest.raises(psycopg.errors.IntegrityError) as raised:
        yield

    message = str(raised.value)
    assert constraint in message, (
        f"the row was rejected, but not by {constraint}. Something else refused it "
        f"first, so that constraint is still unproven:\n{message}"
    )


class TestAuditLogs:
    def test_a_valid_row_is_accepted(self, migrated_connection: psycopg.Connection) -> None:
        """Anchor the rest: if this failed, every rejection below would be vacuous."""

        insert_audit(migrated_connection)

        count = migrated_connection.execute("SELECT count(*) FROM audit_logs").fetchone()
        assert count is not None and count[0] == 1

    def test_an_unknown_actor_type_is_rejected(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        with rejected_by("ck_audit_logs_actor_type"):
            insert_audit(migrated_connection, actor_type="root", actor_id=ACTOR)

    def test_a_human_actor_without_an_id_is_rejected(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        """An admin action with a null actor is indistinguishable from a cron job."""

        with rejected_by("ck_audit_logs_human_actor_is_identified"):
            insert_audit(migrated_connection, actor_type="admin_user", actor_id=None)

    def test_a_system_actor_carrying_an_id_is_rejected(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        with rejected_by("ck_audit_logs_human_actor_is_identified"):
            insert_audit(migrated_connection, actor_type="system_worker", actor_id=ACTOR)

    def test_a_system_actor_without_an_id_is_accepted(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        insert_audit(migrated_connection, actor_type="system_maintenance", actor_id=None)

    def test_a_blank_action_is_rejected(self, migrated_connection: psycopg.Connection) -> None:
        """NOT NULL alone would let '   ' through, which reads as a real action."""

        with rejected_by("ck_audit_logs_action_not_blank"):
            insert_audit(migrated_connection, action="   ")

    def test_metadata_descriptors_are_mandatory(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        """Metadata may extend an event; it may never arrive undescribed."""

        with pytest.raises(psycopg.errors.NotNullViolation):
            migrated_connection.execute(
                "INSERT INTO audit_logs (action, outcome, actor_type, actor_id, metadata_version) "
                "VALUES ('x.y', 'success', 'admin_user', %s, 1)",
                (ACTOR,),
            )

    def test_defaults_fill_metadata_role_snapshot_and_schema_version(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        insert_audit(migrated_connection)

        row = migrated_connection.execute(
            "SELECT metadata, actor_role_snapshot, audit_schema_version FROM audit_logs"
        ).fetchone()

        assert row is not None
        # An object and an array, not both '{}'. A consumer iterating the snapshot
        # would otherwise have to check the shape before every use.
        assert row[0] == {}
        assert row[1] == []
        assert row[2] == 1

    def test_sequence_numbers_are_assigned_and_ordered(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        """The ordering key a cursor needs when two rows share a timestamp."""

        for index in range(3):
            insert_audit(migrated_connection, action=f"center_profile.step_{index}")

        rows = migrated_connection.execute(
            "SELECT sequence_number FROM audit_logs ORDER BY sequence_number"
        ).fetchall()
        numbers = [row[0] for row in rows]

        assert len(numbers) == 3
        assert numbers == sorted(numbers)
        assert len(set(numbers)) == 3

    def test_a_supplied_sequence_number_does_not_collide_silently(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        """GENERATED BY DEFAULT allows an override; the unique index catches reuse.

        Worth pinning: `BY DEFAULT` rather than `ALWAYS` is what makes a restore
        that carries its own values possible, and the cost is that a caller can
        collide. The index is what turns that into an error instead of duplicate
        cursor positions.
        """

        migrated_connection.execute(
            "INSERT INTO audit_logs "
            f"(sequence_number, {AUDIT_COLUMNS}) VALUES (900001, {AUDIT_VALUES})",
            AUDIT_DEFAULTS,
        )
        with rejected_by("uq_audit_logs_sequence_number"):
            migrated_connection.execute(
                "INSERT INTO audit_logs "
                f"(sequence_number, {AUDIT_COLUMNS}) VALUES (900001, {AUDIT_VALUES})",
                AUDIT_DEFAULTS,
            )


class TestOutboxEvents:
    def insert(self, connection: psycopg.Connection, **overrides: object) -> None:
        values: dict[str, object] = {
            "aggregate_type": "center_profile",
            "aggregate_id": uuid.uuid4(),
            "aggregate_version": 1,
            "event_type": "CenterProfileRenamed",
            "payload": '{"name": "x"}',
            "payload_version": 1,
            "status": "pending",
            "published_at": None,
            **overrides,
        }
        connection.execute(
            "INSERT INTO outbox_events (aggregate_type, aggregate_id, aggregate_version, "
            "event_type, payload, payload_version, status, published_at) VALUES "
            "(%(aggregate_type)s, %(aggregate_id)s, %(aggregate_version)s, %(event_type)s, "
            "%(payload)s, %(payload_version)s, %(status)s, %(published_at)s)",
            values,
        )

    def test_a_valid_pending_row_is_accepted(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        self.insert(migrated_connection)

        row = migrated_connection.execute(
            "SELECT status, attempt_count, headers FROM outbox_events"
        ).fetchone()

        assert row is not None
        assert row[0] == "pending"
        assert row[1] == 0
        assert row[2] == {}

    def test_retry_is_not_an_accepted_status(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        """`retry` is an unresolved alias in the catalogue, modelled as failed + available_at.

        If this ever passes, the five-value set has been widened by something
        other than an owner decision.
        """

        with rejected_by("ck_outbox_events_status"):
            self.insert(migrated_connection, status="retry")

    @pytest.mark.parametrize(
        "status", ["pending", "processing", "published", "failed", "dead_lettered"]
    )
    def test_every_canonical_status_is_accepted(
        self, migrated_connection: psycopg.Connection, status: str
    ) -> None:
        published_at = "2026-08-01T00:00:00+00:00" if status == "published" else None
        self.insert(migrated_connection, status=status, published_at=published_at)

    def test_published_without_a_timestamp_is_rejected(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        with rejected_by("ck_outbox_events_published_at_matches_status"):
            self.insert(migrated_connection, status="published", published_at=None)

    def test_unpublished_with_a_timestamp_is_rejected(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        with rejected_by("ck_outbox_events_published_at_matches_status"):
            self.insert(
                migrated_connection, status="pending", published_at="2026-08-01T00:00:00+00:00"
            )

    def test_half_a_lock_is_rejected(self, migrated_connection: psycopg.Connection) -> None:
        with rejected_by("ck_outbox_events_lock_fields_move_together"):
            migrated_connection.execute(
                "INSERT INTO outbox_events (aggregate_type, aggregate_id, aggregate_version, "
                "event_type, payload, payload_version, locked_at) VALUES "
                "('center_profile', %s, 1, 'X', '{}', 1, now())",
                (uuid.uuid4(),),
            )

    def test_the_dispatch_index_covers_only_the_claimable_set(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        """The predicate is the decision doc 04 got wrong; assert it from the catalogue.

        Read back from pg_indexes rather than trusted from the migration source,
        so an edit to either that does not reach the database is visible.
        """

        definition = migrated_connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_outbox_dispatch'"
        ).fetchone()

        assert definition is not None
        predicate = definition[0]
        for claimable in ("pending", "processing", "failed"):
            assert f"'{claimable}'" in predicate
        assert "retry" not in predicate
        assert "published" not in predicate
        assert "dead_lettered" not in predicate


class TestIdempotencyRecords:
    def insert(self, connection: psycopg.Connection, **overrides: object) -> None:
        values: dict[str, object] = {
            "actor_type": "trader_user",
            "actor_id": ACTOR,
            "operation": "center_profile.rename",
            "idempotency_key": "key-1",
            "request_hash": "a" * 64,
            "status": "in_progress",
            "expires_at": "2030-01-01T00:00:00+00:00",
            **overrides,
        }
        connection.execute(
            "INSERT INTO idempotency_records (actor_type, actor_id, operation, "
            "idempotency_key, request_hash, status, expires_at) VALUES "
            "(%(actor_type)s, %(actor_id)s, %(operation)s, %(idempotency_key)s, "
            "%(request_hash)s, %(status)s, %(expires_at)s)",
            values,
        )

    def test_a_valid_row_is_accepted(self, migrated_connection: psycopg.Connection) -> None:
        self.insert(migrated_connection)

    def test_the_same_key_twice_for_one_actor_and_operation_is_rejected(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        self.insert(migrated_connection)

        with rejected_by("uq_idempotency_records_actor_operation_key"):
            self.insert(migrated_connection)

    def test_the_same_key_for_a_different_actor_is_accepted(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        """The reason the key is four columns.

        Under a global unique key this insert would fail, and the second caller
        would be served the first caller's stored response — a correctness bug and
        a disclosure at once.
        """

        self.insert(migrated_connection)
        self.insert(migrated_connection, actor_id=uuid.uuid4())

    def test_the_same_key_for_a_different_operation_is_accepted(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        self.insert(migrated_connection)
        self.insert(migrated_connection, operation="center_profile.deactivate")

    def test_an_uppercase_request_hash_is_rejected(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        """Two spellings of one digest would silently defeat the same-hash branch."""

        with rejected_by("ck_idempotency_records_request_hash_lowercase"):
            self.insert(migrated_connection, request_hash="A" * 64)

    def test_a_short_request_hash_is_rejected(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        with rejected_by("ck_idempotency_records_request_hash_length"):
            self.insert(migrated_connection, request_hash="a" * 32 + " " * 32)

    def test_an_expiry_before_creation_is_rejected(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        with rejected_by("ck_idempotency_records_expires_after_creation"):
            self.insert(migrated_connection, expires_at="2000-01-01T00:00:00+00:00")

    def test_status_has_no_value_check(self, migrated_connection: psycopg.Connection) -> None:
        """A deliberate omission, not an oversight.

        `status_catalog.yaml` records this aggregate with `canonical: null`, so
        enumerating the values in a migration would decide an open question. If
        someone adds the CHECK without the owner decision, this test fails and
        says why.
        """

        self.insert(migrated_connection, status="a-value-no-catalogue-approved")


class TestCenterProfile:
    def insert(self, connection: psycopg.Connection, **overrides: object) -> None:
        values: dict[str, object] = {
            "name": "Golden Center",
            "status": "active",
            "default_currency": "IRR",
            **overrides,
        }
        connection.execute(
            "INSERT INTO center_profile (name, status, default_currency) VALUES "
            "(%(name)s, %(status)s, %(default_currency)s)",
            values,
        )

    def test_a_valid_row_is_accepted_with_its_defaults(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        self.insert(migrated_connection)

        row = migrated_connection.execute(
            "SELECT timezone, record_version, default_currency FROM center_profile"
        ).fetchone()

        assert row is not None
        assert row[0] == "Asia/Tehran"
        assert row[1] == 1
        assert row[2] == "IRR"

    def test_a_second_active_profile_is_rejected(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        """A deployment singleton, enforced by the database rather than by hope."""

        self.insert(migrated_connection)

        with rejected_by("uq_center_profile_one_active"):
            self.insert(migrated_connection, name="Second Center")

    def test_a_second_inactive_profile_is_accepted(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        """The index is partial; only `active` is constrained.

        Without this, replacing a profile would require deleting history.
        """

        self.insert(migrated_connection)
        self.insert(migrated_connection, name="Retired Center", status="retired")
        self.insert(migrated_connection, name="Older Center", status="retired")

    def test_a_non_irr_currency_is_rejected(
        self, migrated_connection: psycopg.Connection
    ) -> None:
        with rejected_by("ck_center_profile_default_currency_is_irr"):
            self.insert(migrated_connection, default_currency="USD")

    def test_a_blank_name_is_rejected(self, migrated_connection: psycopg.Connection) -> None:
        with rejected_by("ck_center_profile_name_not_blank"):
            self.insert(migrated_connection, name="  ")
