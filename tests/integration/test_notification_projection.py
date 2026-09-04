"""Outbox events become messages, and a failed message changes no money.

M9 slice 7, against a real PostgreSQL. `04_Database_Schema.md` §13.3, the plan's G-2 and G-5.

**This is the consumer M2 said did not exist**, and the two properties that matter are opposites:

- `OPS-NOTIFY-002` — a confirmed failure produces a notification. G-5 decided that a failed payment
  is *told* rather than published, on the grounds that `PaymentAttemptFailed` was already being
  enqueued and only needed a reader. Without this test that decision is a sentence in a plan.
- `OPS-NOTIFY-001` — a notification that cannot be written changes nothing financial. §17 `:1185`
  lists it among M9's ten tests, and it is the one that says the projection is a projection.

**At-least-once is exercised, not assumed.** The dispatcher is run twice over the same event and
the second pass must produce no second message — which is what `uq_notification_dedup` is for, and
what `audit_outbox_catalog.yaml`'s `consumer_deduplication_key: outbox_event_id` names.

Covers: OPS-NOTIFY-001, OPS-NOTIFY-002.
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

TRADER_PHONE = "+989120010001"
IBAN = "IR060120000000000000000100"
AMOUNT = 500_000_000


@pytest.fixture(scope="module")
def migrated(module_provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        module_provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=module_provisioned_database.app_role,
        worker_role=module_provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return module_provisioned_database


@pytest.fixture(scope="module")
def world(migrated: RuntimeIdentities, tmp_path_factory: Any) -> Iterator[dict[str, Any]]:
    from app.core.config import Settings
    from app.core.runtime import RuntimeServices

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=tmp_path_factory.mktemp("notification-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="n" * 40,
        auth_rate_limit_key_secret=None,
    )

    ids = {
        name: uuid.uuid4()
        for name in ("trader", "beneficiary", "profile", "version", "account")
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Notified Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', 'x', 'active', TRUE)",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Fourteen', %s, %s, 'active', "
            "'not_checked')",
            (ids["beneficiary"], ids["trader"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'tejarat', 'Bank Tejarat', 'active')",
            (ids["profile"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', 1000000000, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], "a" * 64),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, iban, "
            "normalized_iban, account_role, status) "
            "VALUES (%s, %s, 'Centre Account', %s, %s, 'outgoing_source', 'active')",
            (ids["account"], ids["profile"], IBAN, IBAN),
        )
        connection.commit()

    runtime = RuntimeServices.from_settings(settings)
    yield {
        "runtime": runtime,
        "owner_url": migrated.owner_url,
        "app_role": migrated.app_role,
        **{f"{name}_id": value for name, value in ids.items()},
    }
    runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(autouse=True)
def a_quiet_outbox(world: dict[str, Any]) -> Iterator[None]:
    """Empty the outbox and the notifications before each test.

    **The dispatcher claims every pending event, not this test's.** The database is module-scoped,
    so a test that asserts `report.published == 1` was really asserting "no earlier test left
    anything behind" — and three did. The counts are the honest thing to assert against a batch
    dispatcher, so the batch is what gets controlled.
    """

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute("DELETE FROM notifications")
        connection.execute("DELETE FROM outbox_events")
        connection.commit()
    yield


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def a_request_with_a_failed_attempt(world: dict[str, Any]) -> dict[str, Any]:
    """One request, one revision, one `failed` attempt. The state slice 3 leaves behind."""

    request_id = uuid.uuid4()
    revision_id = uuid.uuid4()
    attempt_id = uuid.uuid4()

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
            "status, record_version) VALUES (%s, %s, %s, %s, 'sent_to_bank', 1)",
            (
                request_id,
                world["trader_id"],
                world["beneficiary_id"],
                f"PR-{str(request_id)[:8]}",
            ),
        )
        connection.execute(
            "INSERT INTO payment_request_revisions (id, payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
            "content_hash, created_by_actor_type) "
            "VALUES (%s, %s, 1, %s, 'Ali Fourteen', %s, %s, %s, 'trader_user')",
            (revision_id, request_id, world["beneficiary_id"], IBAN, AMOUNT, "c" * 64),
        )
        connection.execute(
            "UPDATE payment_requests SET current_revision_id = %s WHERE id = %s",
            (revision_id, request_id),
        )
        connection.execute(
            "INSERT INTO payment_attempts (id, payment_request_id, "
            "payment_request_revision_id, attempt_number, attempt_type, amount_irr, "
            "beneficiary_name_snapshot, beneficiary_iban_snapshot, bank_profile_version_id, "
            "bank_account_id, split_rule_snapshot, status, failure_code, failure_reason, "
            "record_version) "
            "VALUES (%s, %s, %s, 1, 'original', %s, 'Ali Fourteen', %s, %s, %s, '{}', 'failed', "
            "'bank_rejected', 'Bank rejected this row.', 1)",
            (
                attempt_id,
                request_id,
                revision_id,
                AMOUNT,
                IBAN,
                world["version_id"],
                world["account_id"],
            ),
        )
        connection.commit()

    return {"request_id": request_id, "attempt_id": attempt_id}


def an_event(
    world: dict[str, Any], event_type: str, payload: dict[str, Any], aggregate_id: uuid.UUID
) -> uuid.UUID:
    event_id = uuid.uuid4()
    import json

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO outbox_events (id, aggregate_type, aggregate_id, aggregate_version, "
            "event_type, payload, payload_version, headers, status, available_at, attempt_count) "
            "VALUES (%s, 'payment_attempt', %s, 1, %s, %s, 1, '{}', 'pending', now(), 0)",
            (event_id, aggregate_id, event_type, json.dumps(payload)),
        )
        connection.commit()
    return event_id


def run_dispatch(world: dict[str, Any], *, deliver: Any = None) -> Any:
    from app.notifications.projection import notification_deliverer
    from app.workers.dispatcher import dispatch_once

    runtime = world["runtime"]
    return dispatch_once(
        runtime.uow_factory,
        deliver or notification_deliverer(runtime.uow_factory),
        worker_id="test-dispatcher",
    )


def notifications_for(world: dict[str, Any], request_id: uuid.UUID) -> list[tuple[Any, ...]]:
    return rows(
        world,
        "SELECT notification_type, title, body, entity_type, status, deduplication_key "
        "FROM notifications WHERE entity_id = %s OR body LIKE %s",
        request_id,
        f"%{str(request_id)[:8]}%",
    )


def financial_snapshot(world: dict[str, Any], case: dict[str, Any]) -> Any:
    return rows(
        world,
        "SELECT row_to_json(t) FROM (SELECT * FROM payment_attempts WHERE id = %s) t",
        case["attempt_id"],
    )[0][0]


def test_a_confirmed_failure_reaches_its_trader(world: dict[str, Any]) -> None:
    """`OPS-NOTIFY-002`. G-5's decision, made real.

    `PaymentAttemptFailed` has been enqueued since slice 3 and read by nothing. The plan decided a
    failed payment is told rather than published *because* this event existed; that argument is
    only honest once something consumes it.
    """

    case = a_request_with_a_failed_attempt(world)
    an_event(
        world,
        "PaymentAttemptFailed",
        {
            "payment_attempt_id": str(case["attempt_id"]),
            "payment_request_id": str(case["request_id"]),
            "failure_code": "bank_rejected",
        },
        case["attempt_id"],
    )

    report = run_dispatch(world)
    assert report.published == 1, f"the event was not delivered: {report}"

    messages = notifications_for(world, case["request_id"])
    assert len(messages) == 1, f"expected one notification, got {messages}"
    assert messages[0][0] == "payment_attempt_failed"
    assert "did not succeed" in messages[0][2]
    assert "bank_rejected" in messages[0][2]
    assert messages[0][4] == "unread"


def test_a_notification_carries_no_amount_and_no_iban(world: dict[str, Any]) -> None:
    """A message is delivered outside the authenticated surface in every channel ADR-009 might pick.

    So a figure in the body is a figure on somebody's lock screen. The request number is enough to
    open the right screen, and the entity reference is what opens it.
    """

    case = a_request_with_a_failed_attempt(world)
    an_event(
        world,
        "PaymentAttemptFailed",
        {
            "payment_attempt_id": str(case["attempt_id"]),
            "payment_request_id": str(case["request_id"]),
            "failure_code": "bank_rejected",
            # **The payload carries the amount and the IBAN on purpose.** The first version of
            # this test used a payload with neither, so the assertions below could not have
            # failed however carelessly the message was written — a gate whose input made it
            # unable to fail, and a negative control proved it by adding
            # `payload.get("amount_irr")` to the body and going uncaught. Slice 3's
            # `PaymentAttemptPaid` really does carry `amount_irr`, so this is the realistic
            # shape rather than a contrived one.
            "amount_irr": str(AMOUNT),
            "beneficiary_iban": IBAN,
        },
        case["attempt_id"],
    )
    assert run_dispatch(world).published == 1

    messages = notifications_for(world, case["request_id"])
    body = messages[0][2] + messages[0][1]
    assert IBAN not in body, "an IBAN reached a notification body"
    assert str(AMOUNT) not in body, "an amount reached a notification body"
    assert "500,000,000" not in body


def test_the_same_event_twice_produces_one_message(world: dict[str, Any]) -> None:
    """At-least-once delivery, and `uq_notification_dedup` is what makes it harmless.

    The event's status is put back to `pending` between passes, which is exactly what a crash
    between delivery and commit would leave behind — the situation the dedup key exists for rather
    than a contrived one.
    """

    case = a_request_with_a_failed_attempt(world)
    event_id = an_event(
        world,
        "PaymentAttemptFailed",
        {
            "payment_attempt_id": str(case["attempt_id"]),
            "payment_request_id": str(case["request_id"]),
        },
        case["attempt_id"],
    )
    assert run_dispatch(world).published == 1

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            # `published_at` is cleared with the status: `ck_outbox_events_published_at_matches_
            # status` refuses a pending row that claims a publication time, which is the table
            # keeping its own record honest.
            "UPDATE outbox_events SET status = 'pending', published_at = NULL, "
            "locked_at = NULL, locked_by = NULL, available_at = now() WHERE id = %s",
            (event_id,),
        )
        connection.commit()

    second = run_dispatch(world)
    assert second.claimed == 1, "the redelivered event was not claimed"
    assert len(notifications_for(world, case["request_id"])) == 1, (
        "the same event produced a second message. `audit_outbox_catalog.yaml` names "
        "`outbox_event_id` as the consumer deduplication key and §13.3 gives the index; "
        "at-least-once delivery means this happens for real."
    )


def test_an_unhandled_event_type_is_not_a_failure(world: dict[str, Any]) -> None:
    """Eleven event types exist and this consumer reads three.

    Raising on the rest would dead-letter events behaving exactly as designed, and the dispatcher
    would report a fault every time a batch was approved.
    """

    case = a_request_with_a_failed_attempt(world)
    an_event(
        world,
        "PaymentBatchVersionApproved",
        {"payment_request_id": str(case["request_id"])},
        case["attempt_id"],
    )

    report = run_dispatch(world)
    assert report.published == 1, f"an unread event type was treated as a fault: {report}"
    assert report.failed == 0
    assert notifications_for(world, case["request_id"]) == []


def test_a_failing_notification_rolls_back_no_financial_state(
    world: dict[str, Any],
) -> None:
    """`OPS-NOTIFY-001`. §17 `:1185`, and the reason the dispatcher has its own transaction.

    The projection is made to raise. The attempt was committed one transaction earlier, so it must
    be untouched — and the event must be left retryable rather than published, because the message
    genuinely was not delivered.
    """

    case = a_request_with_a_failed_attempt(world)
    event_id = an_event(
        world,
        "PaymentAttemptFailed",
        {
            "payment_attempt_id": str(case["attempt_id"]),
            "payment_request_id": str(case["request_id"]),
        },
        case["attempt_id"],
    )
    before = financial_snapshot(world, case)

    def explode(_event: Any) -> None:
        raise RuntimeError("the notification channel is down")

    report = run_dispatch(world, deliver=explode)
    assert report.failed == 1, f"the failure was not recorded as one: {report}"

    assert financial_snapshot(world, case) == before, (
        "a notification failure changed a bank fact. The dispatcher runs post-commit in its own "
        "transaction precisely so that it cannot."
    )
    assert notifications_for(world, case["request_id"]) == []

    status = rows(world, "SELECT status FROM outbox_events WHERE id = %s", event_id)[0][0]
    assert status == "failed", (
        f"the undelivered event is {status}; it must stay retryable, or the trader is never told "
        "and nothing says so"
    )


def test_an_event_naming_no_request_is_a_retryable_fault(world: dict[str, Any]) -> None:
    """A payload without `payment_request_id` is a producer and a consumer disagreeing.

    Not ignored: ignoring it would drop a message silently, and the dead-letter path exists so that
    somebody eventually looks. Distinct from an unhandled *event type*, which is normal.
    """

    an_event(
        world,
        "PaymentAttemptFailed",
        {"payment_attempt_id": str(uuid.uuid4())},
        uuid.uuid4(),
    )

    report = run_dispatch(world)
    assert report.failed == 1, f"a malformed payload was published anyway: {report}"


def test_the_runtime_role_cannot_change_what_a_notification_says(world: dict[str, Any]) -> None:
    """Insert-only in every column except the two that record having read it.

    Nothing checked this table's privileges until a negative control went uncaught: adding
    `GRANT UPDATE` to M9's migration was **NOT CAUGHT**, because
    `test_batching_table_privileges.py`'s matrix is M6's and stops at the batching tables. This
    test was written then, and asserted that the runtime role could update nothing at all.

    **M11 slice 1 narrowed it rather than deleting it**, which is the point of this note. The
    slice's `20260913_0044` grants UPDATE on `status` and `read_at`, because a notification can now
    be marked read — so the old assertion is now false, and the honest response to a gate that
    contradicts a deliberate change is to make it say the sharper thing rather than to remove it.

    The sharper thing is: everything a person was *told* is still unwritable. The title, the body,
    the type, the entity it points at, the recipient it was addressed to, and the deduplication key
    that makes at-least-once delivery produce one message. A notification whose text could change
    after it was sent is not a record of what somebody was told, and a writable
    `deduplication_key` is one a redelivery could dodge.

    Asserted against the **runtime role**, not the owner, for the reason that file records at
    length: `SET ROLE` does not survive a `ROLLBACK`, and a check run as the owner would pass
    against a table with every grant.
    """

    case = a_request_with_a_failed_attempt(world)
    an_event(
        world,
        "PaymentAttemptFailed",
        {
            "payment_attempt_id": str(case["attempt_id"]),
            "payment_request_id": str(case["request_id"]),
        },
        case["attempt_id"],
    )
    assert run_dispatch(world).published == 1

    # Every column of the table except the two the slice granted. Listed rather than derived, so
    # that a column added later is a test failure asking which side of the line it belongs on.
    withheld = {
        "recipient_actor_type": "'admin_user'",
        "recipient_actor_id": "gen_random_uuid()",
        "notification_type": "'payment_result_published'",
        "title": "'something else'",
        "body": "'something else'",
        "entity_type": "'payment_request'",
        "entity_id": "gen_random_uuid()",
        "deduplication_key": "'forged'",
        "created_at": "now()",
    }

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(f'SET ROLE "{world["app_role"]}"')
        for column, value in withheld.items():
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"UPDATE notifications SET {column} = {value}")
            connection.rollback()
            connection.execute(f'SET ROLE "{world["app_role"]}"')
        connection.rollback()


def test_the_runtime_role_can_record_that_one_was_read(world: dict[str, Any]) -> None:
    """The other half, and the reason it is a separate test.

    A grant nothing exercises is indistinguishable from a grant that was never written — and this
    project has shipped that mistake enough times to name it. `20260913_0044` claims the runtime
    can write `status` and `read_at`; if it could not, `mark-all-read` would fail in production
    against a schema every migration test calls correct.

    The test above and this one are the two directions of one line, and neither is sufficient
    alone: the first passes against a table with no grants at all, and the second against a table
    with every grant.
    """

    case = a_request_with_a_failed_attempt(world)
    an_event(
        world,
        "PaymentAttemptFailed",
        {
            "payment_attempt_id": str(case["attempt_id"]),
            "payment_request_id": str(case["request_id"]),
        },
        case["attempt_id"],
    )
    assert run_dispatch(world).published == 1

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(f'SET ROLE "{world["app_role"]}"')
        connection.execute("UPDATE notifications SET status = 'read', read_at = now()")
        connection.rollback()


def test_every_handled_event_name_is_one_the_catalogue_lists(world: dict[str, Any]) -> None:
    """The mapping's keys are a contract with `audit_outbox_catalog.yaml`.

    An event renamed there and not here stops producing notifications **silently**, which is the
    worst failure this table can have: nobody is told and nothing reports it. Checked against the
    catalogue file rather than against the registry, because the catalogue is what M0 approved.
    """

    import json
    from pathlib import Path

    from app.notifications.projection import HANDLED_EVENTS

    catalogue = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "governance"
            / "audit_outbox_catalog.yaml"
        ).read_text(encoding="utf-8")
    )
    approved = set(catalogue["outbox_events"])

    unknown = sorted(set(HANDLED_EVENTS) - approved)
    assert unknown == [], (
        f"the projection reads {unknown}, which `audit_outbox_catalog.yaml` does not list. Either "
        "the event was renamed and this mapping was not, or the projection invented a name — and "
        "both mean traders stop being told without anything failing."
    )
