"""A trader's claim to have paid, and everything it must not do.

M10 slice 2, against a real PostgreSQL. `05_API_Specification.md` §21.3,
`04_Database_Schema.md` §10.3.

**The slice is one sentence and one test.** §21.3: "Uploading evidence never confirms payment." So
`SVC-RECEIPT-001` submits a claim and reads back both the receipt and the order, requiring
`confirmed_amount_irr` to be null, `confirmed_at` to be null, and the order to be
`payment_evidence_submitted` rather than any confirmed state. A test that only checked the receipt
was created would pass against an implementation that helpfully marked the order paid — which is
the shape M9 met four times.

Covers: SEC-RECEIPT-001, SVC-RECEIPT-001.
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

PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "X-CSRF-Token"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"

OWNER_PHONE = "+989120013001"
OTHER_PHONE = "+989120013002"

CLAIMED = 10_040_000_000


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
    from app.main import create_app
    from app.security.passwords import Argon2Parameters, hash_password
    from fastapi.testclient import TestClient

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=tmp_path_factory.mktemp("receipt-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="r" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {name: uuid.uuid4() for name in ("owner", "other", "trader_file", "admin_file")}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for key, phone, name in (
            ("owner", OWNER_PHONE, "Paying Trader"),
            ("other", OTHER_PHONE, "Other Trader"),
        ):
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, 'active', 'approved')",
                (ids[key], name, phone),
            )
            connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, %s, %s, 'active', TRUE)",
                (ids[key], phone, f"{name} Contact", encoded),
            )
        # Two files: one a trader uploaded, one an admin did. The difference is the whole of
        # `SEC-RECEIPT-001` — a claim may not cite a document the trader never sent.
        for key, uploader in (("trader_file", "trader_user"), ("admin_file", "admin_user")):
            connection.execute(
                "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
                "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
                "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
                "original_or_derived_relation, metadata) "
                "VALUES (%s, 'local', 'gold', %s, 'receipt.png', 'image/png', 512, %s, "
                "'incoming_payment_receipt', 'internal', 'available', 'clean', %s, "
                "'original', '{}')",
                (ids[key], f"receipts/{ids[key]}", "a" * 64, uploader),
            )
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES ('receipt_accountant', 'Accountant', %s, 'active')",
            (encoded,),
        )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = 'receipt_accountant' AND r.code = 'accountant'"
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as client:
        yield {
            "client": client,
            "owner_url": migrated.owner_url,
            "app_role": migrated.app_role,
            **{f"{name}_id": value for name, value in ids.items()},
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def sign_in_trader(world: dict[str, Any], phone: str) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": phone, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def sign_in_admin(world: dict[str, Any], username: str) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(world: dict[str, Any]) -> dict[str, str]:
    client = world["client"]
    token = client.cookies.get(TRADER_CSRF_COOKIE) or client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def a_priced_order(world: dict[str, Any], *, trader_key: str = "owner") -> str:
    """An order the centre has priced, which is where a payment claim becomes possible.

    Written directly rather than driven through slice 1's routes: this module's subject is the
    claim, and slice 1's own tests prove the pricing path.
    """

    order_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO gold_sale_orders (id, trader_id, order_number, status, gold_type, "
            "gold_weight, weight_unit, gold_purity, expected_amount_irr, created_by_actor_type, "
            "record_version) VALUES (%s, %s, %s, 'priced', 'bullion', 125.500000, 'GRAM', "
            "'18K', %s, 'trader_user', 1)",
            (order_id, world[f"{trader_key}_id"], f"GS-{str(order_id)[:8]}", CLAIMED),
        )
        connection.commit()
    return str(order_id)


def submit_receipt(world: dict[str, Any], order_id: str, **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {"amount_irr": CLAIMED}
    body.update(overrides)
    return client.post(
        f"/api/v1/gold-sale-orders/{order_id}/incoming-payment-receipts",
        json=body,
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )


def receipts_of(world: dict[str, Any], order_id: str) -> list[tuple[Any, ...]]:
    return rows(
        world,
        "SELECT status, amount_irr, confirmed_amount_irr, confirmed_at, "
        "confirmed_by_admin_user_id FROM incoming_payment_receipts "
        "WHERE gold_sale_order_id = %s ORDER BY created_at",
        order_id,
    )


def test_a_claim_confirms_nothing(world: dict[str, Any]) -> None:
    """`SVC-RECEIPT-001`. §21.3: "Uploading evidence never confirms payment."

    **The test that would pass against almost anything if it only checked the receipt existed.**
    Both the receipt and the order are read back: the confirmation columns must be null and the
    order must be `payment_evidence_submitted`, which §10.1 places four states before
    `incoming_payment_confirmed`.
    """

    order_id = a_priced_order(world)
    sign_in_trader(world, OWNER_PHONE)

    response = submit_receipt(world, order_id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "submitted"
    assert body["amount_irr"] == CLAIMED
    assert body["confirmed_amount_irr"] is None, (
        "a claim came back with a confirmed amount. §21.3 says uploading evidence never confirms "
        "payment, and slice 6 is what confirms it against a bank statement."
    )
    assert body["order_status"] == "payment_evidence_submitted"

    stored = receipts_of(world, order_id)
    assert len(stored) == 1
    assert stored[0][2] is None, "confirmed_amount_irr was written by the claim"
    assert stored[0][3] is None, "confirmed_at was written by the claim"
    assert stored[0][4] is None, "a confirming actor was recorded for an unconfirmed claim"

    order_status = rows(
        world, "SELECT status FROM gold_sale_orders WHERE id = %s", order_id
    )[0][0]
    assert order_status == "payment_evidence_submitted", (
        f"the order is {order_status}. A claim moves it to evidence-submitted and no further; "
        "anything past that is the centre agreeing with a figure it has not checked."
    )


def test_the_body_cannot_carry_a_confirmation(world: dict[str, Any]) -> None:
    """The absence, asserted at the boundary rather than by a rejected value.

    `extra="forbid"` turns an attempt into a 422, and the field genuinely does not exist — which
    survives somebody relaxing a validator in a way a rejection would not.
    """

    order_id = a_priced_order(world)
    sign_in_trader(world, OWNER_PHONE)

    assert submit_receipt(world, order_id, confirmed_amount_irr=CLAIMED).status_code == 422
    assert submit_receipt(world, order_id, status="confirmed").status_code == 422
    assert receipts_of(world, order_id) == []


def test_two_claims_are_both_recorded(world: dict[str, Any]) -> None:
    """A trader may pay in instalments, and §10.3 has no unique that would refuse the second.

    This is why the route takes no `If-Match`: a second receipt is not a conflicting edit of the
    first, and requiring the order's version would make a legitimate second payment a 412.
    """

    order_id = a_priced_order(world)
    sign_in_trader(world, OWNER_PHONE)

    assert submit_receipt(world, order_id, amount_irr=4_000_000_000).status_code == 201
    assert submit_receipt(world, order_id, amount_irr=6_040_000_000).status_code == 201

    stored = receipts_of(world, order_id)
    assert len(stored) == 2, stored
    assert {row[1] for row in stored} == {4_000_000_000, 6_040_000_000}


def test_a_claim_may_cite_the_traders_own_file(world: dict[str, Any]) -> None:
    order_id = a_priced_order(world)
    sign_in_trader(world, OWNER_PHONE)

    response = submit_receipt(
        world, order_id, evidence_file_id=str(world["trader_file_id"])
    )
    assert response.status_code == 201, response.text
    assert response.json()["evidence_file_id"] == str(world["trader_file_id"])


def test_a_claim_cannot_cite_an_internal_document(world: dict[str, Any]) -> None:
    """`SEC-RECEIPT-001`. Attaching a document the trader never sent as proof that they sent it.

    The file exists and is available, so nothing about it looks wrong — what is wrong is who
    uploaded it, which is the only question this slice can answer honestly about a file.
    """

    order_id = a_priced_order(world)
    sign_in_trader(world, OWNER_PHONE)

    response = submit_receipt(
        world, order_id, evidence_file_id=str(world["admin_file_id"])
    )
    assert response.status_code == 400, response.text
    assert "not uploaded by a trader" in response.text
    assert receipts_of(world, order_id) == []


def test_another_trader_cannot_claim_against_this_order(world: dict[str, Any]) -> None:
    """404, not 403 — an authorisation error would confirm the order exists."""

    order_id = a_priced_order(world, trader_key="owner")
    sign_in_trader(world, OTHER_PHONE)

    response = submit_receipt(world, order_id)
    assert response.status_code == 404, response.text
    assert receipts_of(world, order_id) == []


def test_an_accountant_cannot_claim_on_a_traders_behalf(world: dict[str, Any]) -> None:
    """"The centre says the trader paid" is not "the trader says so".

    Refused rather than quietly attributed: the audit row would otherwise record a trader's claim
    made by somebody else, which is the one thing an evidence trail must never blur.
    """

    order_id = a_priced_order(world)
    sign_in_admin(world, "receipt_accountant")

    response = submit_receipt(world, order_id)
    assert response.status_code == 403, response.text
    assert receipts_of(world, order_id) == []


def test_an_unpriced_order_cannot_be_paid_for(world: dict[str, Any]) -> None:
    """Before the centre has priced it there is no amount to have paid."""

    order_id = a_priced_order(world)
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE gold_sale_orders SET status = 'draft' WHERE id = %s", (order_id,)
        )
        connection.commit()

    sign_in_trader(world, OWNER_PHONE)
    response = submit_receipt(world, order_id)
    assert response.status_code == 400, response.text
    assert "draft" in response.text


def test_submitting_replays_rather_than_claiming_twice(world: dict[str, Any]) -> None:
    """A retried POST returns the receipt that exists.

    Distinct from the two-instalments test above: the same `Idempotency-Key` means "my network
    dropped your answer", and a *new* key means a genuinely second payment.
    """

    order_id = a_priced_order(world)
    sign_in_trader(world, OWNER_PHONE)

    client = world["client"]
    key = str(uuid.uuid4())
    headers = {**csrf(world), "Idempotency-Key": key}
    url = f"/api/v1/gold-sale-orders/{order_id}/incoming-payment-receipts"

    first = client.post(url, json={"amount_irr": CLAIMED}, headers=headers)
    assert first.status_code == 201, first.text
    second = client.post(url, json={"amount_irr": CLAIMED}, headers=headers)
    assert second.status_code == 201, second.text

    assert second.json()["id"] == first.json()["id"]
    assert len(receipts_of(world, order_id)) == 1


def test_the_claim_is_audited_as_a_claim(world: dict[str, Any]) -> None:
    """The audit row carries the *claimed* amount and no confirmed one.

    An entry holding both would read as though the centre had agreed with the figure — which is
    exactly the conflation this slice exists to prevent.
    """

    order_id = a_priced_order(world)
    sign_in_trader(world, OWNER_PHONE)
    response = submit_receipt(world, order_id)
    assert response.status_code == 201, response.text

    entries = rows(
        world,
        "SELECT action, entity_type, new_values FROM audit_logs WHERE entity_id = %s",
        response.json()["id"],
    )
    assert len(entries) == 1, entries
    assert entries[0][0] == "incoming_receipt.submitted"
    assert entries[0][1] == "incoming_payment_receipt"
    assert entries[0][2]["claimed_amount_irr"] == str(CLAIMED)
    assert "confirmed_amount_irr" not in entries[0][2]

    events = rows(
        world,
        "SELECT event_type FROM outbox_events WHERE aggregate_id = %s",
        response.json()["id"],
    )
    assert events == [], (
        f"a claim enqueued {events}. Nothing outside the platform can act on a claim, and the "
        "catalogue lists no gold-sale event at all."
    )


def test_the_runtime_cannot_rewrite_a_claim(world: dict[str, Any]) -> None:
    """The grant, read as a privilege rather than inferred from behaviour.

    `amount_irr`, `tracking_number` and `evidence_file_id` are what the trader claimed. A runtime
    that could rewrite them would make the receipt evidence of nothing — and only a query about
    privileges can see a grant, which is the lesson M9 slice 7B recorded.
    """

    granted = rows(
        world,
        "SELECT DISTINCT column_name FROM information_schema.column_privileges "
        "WHERE table_name = 'incoming_payment_receipts' AND privilege_type = 'UPDATE' "
        "AND grantee = %s ORDER BY column_name",
        world["app_role"],
    )
    assert [row[0] for row in granted] == [
        "confirmed_amount_irr",
        "confirmed_at",
        "confirmed_by_admin_user_id",
        "record_version",
        "status",
        "updated_at",
    ], (
        f"the runtime may update {[row[0] for row in granted]} on a receipt. Everything the "
        "trader claimed must stay frozen; only the lifecycle and the centre's confirmation move."
    )
