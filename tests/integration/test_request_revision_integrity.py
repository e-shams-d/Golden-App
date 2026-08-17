"""What the database refuses about requests and revisions, asked of the database.

M5 slice 3. Two claims, and neither can be proved without PostgreSQL.

**The composite pointer.** `payment_requests.current_revision_id` must name a revision
of *this* request. A single-column foreign key would accept another request's revision:
the pointer would be valid, the row would look correct, and the request would display
somebody else's beneficiary and amount. That is not a bug a code path can be trusted
to avoid, because the wrong value is a legal UUID.

**A revision cannot be updated.** Not through a command — through the *runtime role*,
with direct SQL, one case per column. Every test here connects as the application
identity rather than the owner, for the reason `test_runtime_role_privileges.py`
records: the owner may do anything, so a refusal test run as the owner is never
refused and reports success for a database with no protection at all.

Covers: DB-REV-002, DB-REV-003.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

IBAN = "IR060120000000000000000001"

# Every column of `payment_request_revisions`, with a value of the right type to set
# it to. Enumerated from the model at collection time rather than listed here, so a
# column added later is covered without anyone remembering — see `revision_columns`.
UPDATE_VALUES: dict[str, str] = {
    "id": "gen_random_uuid()",
    "payment_request_id": "gen_random_uuid()",
    "revision_number": "99",
    "beneficiary_id": "gen_random_uuid()",
    "beneficiary_name_snapshot": "'Someone Else'",
    "beneficiary_iban_snapshot": "'IR060120000000000000000009'",
    "beneficiary_national_id_snapshot": "'1234567890'",
    "amount_irr": "999",
    "entered_amount_value": "999",
    "entered_amount_unit": "'TOMAN'",
    "description": "'edited'",
    "source_attachment_file_id": "gen_random_uuid()",
    "revision_reason": "'edited'",
    "content_hash": "repeat('a', 64)",
    "created_by_actor_type": "'admin_user'",
    "created_by_actor_id": "gen_random_uuid()",
    "created_at": "now()",
    "superseded_at": "now()",
}


def revision_columns() -> list[str]:
    """Read from the model so a new column is covered without an edit here.

    `test_every_revision_column_has_a_value_to_try` fails if `UPDATE_VALUES` does not
    cover the model, which is what stops a column added later from being silently
    skipped — the failure mode a hand-written list has.
    """

    import app.db.models  # noqa: F401
    from app.db.base import Base

    return sorted(Base.metadata.tables["payment_request_revisions"].columns.keys())


@pytest.fixture
def migrated_as_migrator(provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=provisioned_database.app_role,
        worker_role=provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return provisioned_database


@pytest.fixture
def seeded(migrated_as_migrator: RuntimeIdentities) -> Iterator[dict[str, Any]]:
    """One trader, one beneficiary, one request and its first revision.

    Written through the owner connection: this fixture is arranging the world, not
    exercising a privilege. The privileges are exercised through `app_url` below.
    """

    trader = uuid.uuid4()
    beneficiary = uuid.uuid4()
    request = uuid.uuid4()
    revision = uuid.uuid4()

    with psycopg.connect(_psycopg(migrated_as_migrator.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Trader', '+989120000099', 'active', 'approved')",
            (trader,),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali', %s, %s, 'active', "
            "'not_checked')",
            (beneficiary, trader, IBAN, IBAN),
        )
        _insert_request_with_revision(connection, trader, beneficiary, request, revision)
        connection.commit()

    yield {
        "identities": migrated_as_migrator,
        "trader": trader,
        "beneficiary": beneficiary,
        "request": request,
        "revision": revision,
    }


def _insert_request_with_revision(
    connection: Any,
    trader: uuid.UUID,
    beneficiary: uuid.UUID,
    request: uuid.UUID,
    revision: uuid.UUID,
    *,
    number: str = "REQ-0001",
) -> None:
    """Both rows in one transaction, which is what the deferrable key is for."""

    connection.execute(
        "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
        "status, current_revision_id) VALUES (%s, %s, %s, %s, 'draft', %s)",
        (request, trader, beneficiary, number, revision),
    )
    connection.execute(
        "INSERT INTO payment_request_revisions (id, payment_request_id, revision_number, "
        "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
        "content_hash, created_by_actor_type) VALUES (%s, %s, 1, %s, 'Ali', %s, 1000, %s, "
        "'trader_user')",
        (revision, request, beneficiary, IBAN, f"{number}-hash".ljust(64, "0")),
    )


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def test_a_request_and_its_first_revision_insert_in_one_transaction(
    seeded: dict[str, Any],
) -> None:
    """DB-REV-002, the permissive half.

    The fixture already did it, so this asserts the result rather than repeating the
    insert — and it is the half that would fail if the key were not deferrable. Each
    row references the other, so whichever went first would violate an immediately
    checked constraint and the ordinary path would be impossible.
    """

    with psycopg.connect(_psycopg(seeded["identities"].owner_url)) as connection:
        row = connection.execute(
            "SELECT r.current_revision_id, v.payment_request_id FROM payment_requests r "
            "JOIN payment_request_revisions v ON v.id = r.current_revision_id "
            "WHERE r.id = %s",
            (seeded["request"],),
        ).fetchone()

    assert row is not None, "the request and its revision are not joinable"
    assert row[0] == seeded["revision"]
    assert row[1] == seeded["request"]


def test_the_pointer_refuses_another_requests_revision(seeded: dict[str, Any]) -> None:
    """DB-REV-002, the whole point.

    A second request is created with its own revision. Pointing the first request at
    the second request's revision is a legal UUID naming a real row, so nothing but
    the composite key can refuse it — and without the refusal the request would show
    the other request's beneficiary and amount while looking entirely correct.
    """

    other_request = uuid.uuid4()
    other_revision = uuid.uuid4()

    with psycopg.connect(_psycopg(seeded["identities"].owner_url)) as connection:
        _insert_request_with_revision(
            connection,
            seeded["trader"],
            seeded["beneficiary"],
            other_request,
            other_revision,
            number="REQ-0002",
        )
        connection.commit()

    with (
        psycopg.connect(_psycopg(seeded["identities"].app_url)) as connection,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        connection.execute(
            "UPDATE payment_requests SET current_revision_id = %s WHERE id = %s",
            (other_revision, seeded["request"]),
        )
        # Deferred, so the violation surfaces at commit rather than at the
        # statement. Asserting without this would pass on a non-deferrable key
        # and on a deferrable one for different reasons.
        connection.commit()


def test_the_pointer_accepts_a_second_revision_of_the_same_request(
    seeded: dict[str, Any],
) -> None:
    """DB-REV-002, guard-the-guard.

    Without this, a key that refused *every* update would satisfy the test above and
    look like working integrity. Moving the pointer to a later revision of the same
    request is the ordinary correction path and must be permitted.
    """

    second = uuid.uuid4()

    with psycopg.connect(_psycopg(seeded["identities"].owner_url)) as connection:
        connection.execute(
            "INSERT INTO payment_request_revisions (id, payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
            "content_hash, created_by_actor_type) VALUES (%s, %s, 2, %s, 'Ali', %s, 2000, %s, "
            "'trader_user')",
            (second, seeded["request"], seeded["beneficiary"], IBAN, "b" * 64),
        )
        connection.commit()

    with psycopg.connect(_psycopg(seeded["identities"].app_url)) as connection:
        connection.execute(
            "UPDATE payment_requests SET current_revision_id = %s WHERE id = %s",
            (second, seeded["request"]),
        )
        connection.commit()

    with psycopg.connect(_psycopg(seeded["identities"].owner_url)) as connection:
        current = connection.execute(
            "SELECT current_revision_id FROM payment_requests WHERE id = %s",
            (seeded["request"],),
        ).fetchone()

    assert current is not None and current[0] == second


@pytest.mark.parametrize("column", revision_columns())
def test_no_column_of_a_revision_can_be_updated(seeded: dict[str, Any], column: str) -> None:
    """DB-REV-003, one case per column.

    Through the runtime role, because that is the identity the application connects
    as and the only one whose refusal means anything. The bootstrap default grants
    `SELECT, INSERT` and the migration adds no UPDATE, so the expected error is a
    privilege refusal rather than a constraint violation — the difference matters,
    because a constraint could be dropped by a later migration while a missing grant
    has to be granted on purpose.

    Parametrised over the model's columns rather than a list written here, so a column
    added in a later slice arrives with a case already covering it.
    """

    value = UPDATE_VALUES[column]

    with (
        psycopg.connect(_psycopg(seeded["identities"].app_url)) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute(
            f'UPDATE payment_request_revisions SET "{column}" = {value} WHERE id = %s',
            (seeded["revision"],),
        )


def test_every_revision_column_has_a_value_to_try() -> None:
    """Guard the guard for the parametrisation above.

    A column missing from `UPDATE_VALUES` would raise `KeyError` inside its own case,
    which reads as a broken test rather than as an uncovered column. This says it
    plainly and fails before the suite runs.
    """

    missing = sorted(set(revision_columns()) - set(UPDATE_VALUES))
    extra = sorted(set(UPDATE_VALUES) - set(revision_columns()))

    assert missing == [], f"revision columns with no update value to try: {missing}"
    assert extra == [], f"update values for columns that no longer exist: {extra}"


def test_the_runtime_role_may_not_delete_a_revision(seeded: dict[str, Any]) -> None:
    """DB-REV-003.

    Immutability that permitted deletion would be immutability in name only: the row
    a dispute is read against could be removed rather than altered, which is the same
    loss by a different verb.
    """

    with (
        psycopg.connect(_psycopg(seeded["identities"].app_url)) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute(
            "DELETE FROM payment_request_revisions WHERE id = %s", (seeded["revision"],)
        )


def test_the_runtime_role_may_insert_a_revision(seeded: dict[str, Any]) -> None:
    """DB-REV-003, guard-the-guard.

    Every refusal above would also hold if the role could not touch the table at all,
    and then the tests would be measuring a table the application cannot use. A
    correction has to be able to write revision 2.
    """

    with psycopg.connect(_psycopg(seeded["identities"].app_url)) as connection:
        connection.execute(
            "INSERT INTO payment_request_revisions (payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
            "content_hash, created_by_actor_type) VALUES (%s, 7, %s, 'Ali', %s, 3000, %s, "
            "'trader_user')",
            (seeded["request"], seeded["beneficiary"], IBAN, "c" * 64),
        )
        connection.commit()


def test_identical_content_within_one_request_is_refused(seeded: dict[str, Any]) -> None:
    """`04_Database_Schema.md:901`, and the constraint that reversed an obligation.

    The M5 plan's slice-5 revision obligation originally claimed identical content
    must be permitted. Document 04 says otherwise and is right: a trader asked to
    correct something who resubmits it unchanged has not corrected it, and a second
    identical revision would reach a reviewer looking like new work.

    The obligation id is deliberately not spelled here. Slice 5 still owes it, and the
    coverage scanner treats any mention in a test file as a citation — so naming it
    would discharge slice 5's work from inside slice 3's comment. That is the sixth
    time in this programme that a mention has been mistaken for a proof, and the
    second time the ledger caught it rather than a reviewer.

    Slice 5 owns the command-level behaviour and the message. This proves the database
    refuses it, so the rule cannot be lost by editing a command.
    """

    with psycopg.connect(_psycopg(seeded["identities"].owner_url)) as connection:
        existing = connection.execute(
            "SELECT content_hash FROM payment_request_revisions WHERE id = %s",
            (seeded["revision"],),
        ).fetchone()

    assert existing is not None

    with (
        psycopg.connect(_psycopg(seeded["identities"].app_url)) as connection,
        pytest.raises(psycopg.errors.UniqueViolation),
    ):
        connection.execute(
            "INSERT INTO payment_request_revisions (payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, "
            "amount_irr, content_hash, created_by_actor_type) VALUES (%s, 2, %s, 'Ali', "
            "%s, 1000, %s, 'trader_user')",
            (seeded["request"], seeded["beneficiary"], IBAN, existing[0]),
        )
        connection.commit()


def test_the_same_content_in_a_different_request_is_permitted(
    seeded: dict[str, Any],
) -> None:
    """The scope of the uniqueness, asserted so it is not widened by accident.

    `UNIQUE(payment_request_id, content_hash)` is per request. Two traders paying the
    same beneficiary the same amount produce identical content, and a global unique
    would refuse the second — one trader's request blocked by another's, with an error
    naming a constraint neither of them can see.
    """

    other_request = uuid.uuid4()
    other_revision = uuid.uuid4()

    with psycopg.connect(_psycopg(seeded["identities"].owner_url)) as connection:
        existing = connection.execute(
            "SELECT content_hash FROM payment_request_revisions WHERE id = %s",
            (seeded["revision"],),
        ).fetchone()
        assert existing is not None

        connection.execute(
            "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
            "status) VALUES (%s, %s, %s, 'REQ-0003', 'draft')",
            (other_request, seeded["trader"], seeded["beneficiary"]),
        )
        connection.execute(
            "INSERT INTO payment_request_revisions (id, payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
            "content_hash, created_by_actor_type) VALUES (%s, %s, 1, %s, 'Ali', %s, 1000, %s, "
            "'trader_user')",
            (other_revision, other_request, seeded["beneficiary"], IBAN, existing[0]),
        )
        connection.commit()

    with psycopg.connect(_psycopg(seeded["identities"].owner_url)) as connection:
        count = connection.execute(
            "SELECT count(*) FROM payment_request_revisions WHERE content_hash = %s",
            (existing[0],),
        ).fetchone()

    assert count is not None and count[0] == 2
