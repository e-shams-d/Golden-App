"""What a trader may see and say, and what saying it must not move.

M9 slice 6, against a real PostgreSQL. `05_API_Specification.md` §20.4-20.6,
`15_Agent_Implementation_Plan.md` §17.6's trader actions.

**The central test reads the money back.** Doc 05 `:1942`: "A dispute creates a visible manual
review task and does not automatically reverse bank facts." So `SVC-DISPUTE-001` snapshots every
column of the attempt and the publication through `row_to_json`, disputes, and requires both
byte-identical. A test that only checked the request's status would pass against an implementation
that helpfully reversed the attempt as well — the same shape as slice 1's acceptance and slice 3B's
retry decision, which is now three times in one milestone.

**A second trader gets 404, not 403**, and the test asserts the *code* rather than the refusal.
An authorisation error over a guessable identifier tells the caller the row exists;
`app/security/ownership.py` records the rule and this is where it is exercised across an aggregate
boundary rather than within one.

Covers: API-PUBLICATION-001, SVC-DISPUTE-001, SVC-ACKNOWLEDGE-001, AUD-PUBLICATION-001.
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
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"
CSRF_HEADER = "X-CSRF-Token"

OWNER_PHONE = "+989120009001"
OTHER_PHONE = "+989120009002"
IBAN = "IR060120000000000000000090"

ACKNOWLEDGE_ACTION = "payment_publication.acknowledged"
DISPUTE_ACTION = "payment_publication.disputed"

AMOUNT = 600_000_000


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
        local_storage_root=tmp_path_factory.mktemp("trader-publication-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="m" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {
        name: uuid.uuid4()
        for name in ("owner", "other", "beneficiary", "profile", "version", "account")
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        # Two traders, because the isolation test needs a *real* second one. A fabricated
        # identifier would prove only that a random UUID is not found.
        for key, phone, name in (
            ("owner", OWNER_PHONE, "Owner Trader"),
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
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Thirteen', %s, %s, 'active', "
            "'not_checked')",
            (ids["beneficiary"], ids["owner"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'saderat', 'Bank Saderat', 'active')",
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
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES ('trader_pub_accountant', 'Accountant', %s, 'active')",
            (encoded,),
        )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = 'trader_pub_accountant' AND r.code = 'accountant'"
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://trader.localhost") as client:
        yield {
            "client": client,
            "owner_url": migrated.owner_url,
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


def csrf(world: dict[str, Any]) -> dict[str, str]:
    client = world["client"]
    token = client.cookies.get(TRADER_CSRF_COOKIE) or client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def admin_id(world: dict[str, Any], username: str) -> uuid.UUID:
    return uuid.UUID(
        str(rows(world, "SELECT id FROM admin_users WHERE username = %s", username)[0][0])
    )


def a_published_request(world: dict[str, Any], *, trader_key: str = "owner") -> dict[str, Any]:
    """A request already at `result_published`, with one paid attempt and one publication.

    Inserted directly. This module's subject is what a *trader* may do; driving five milestones to
    reach a publication would make every test here depend on all of them, and slice 5 already
    proves the publishing path.
    """

    request_id = uuid.uuid4()
    revision_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    publication_id = uuid.uuid4()

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
            "status, result_published_at, record_version) "
            "VALUES (%s, %s, %s, %s, 'result_published', now(), 1)",
            (
                request_id,
                world[f"{trader_key}_id"],
                world["beneficiary_id"],
                f"PR-{str(request_id)[:8]}",
            ),
        )
        connection.execute(
            "INSERT INTO payment_request_revisions (id, payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
            "content_hash, created_by_actor_type) "
            "VALUES (%s, %s, 1, %s, 'Ali Thirteen', %s, %s, %s, 'trader_user')",
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
            "bank_account_id, split_rule_snapshot, status, bank_tracking_number, "
            "bank_result_at, confirmed_by_admin_user_id, confirmed_at, record_version) "
            "VALUES (%s, %s, %s, 1, 'original', %s, 'Ali Thirteen', %s, %s, %s, '{}', 'paid', "
            "'820250901001', now(), %s, now(), 1)",
            (
                attempt_id,
                request_id,
                revision_id,
                AMOUNT,
                IBAN,
                world["version_id"],
                world["account_id"],
                admin_id(world, "trader_pub_accountant"),
            ),
        )
        connection.execute(
            "INSERT INTO payment_result_publications (id, payment_request_id, "
            "publication_version, status, summary_payload, content_hash, "
            "published_by_admin_user_id, published_at) "
            "VALUES (%s, %s, 1, 'active', %s, %s, %s, now())",
            (
                publication_id,
                request_id,
                '{"request_number": "PR-TEST", "amount_irr": "600000000"}',
                "d" * 64,
                admin_id(world, "trader_pub_accountant"),
            ),
        )
        connection.commit()

    return {
        "request_id": request_id,
        "attempt_id": attempt_id,
        "publication_id": publication_id,
    }


def request_version(world: dict[str, Any], request_id: uuid.UUID) -> int:
    return int(
        rows(world, "SELECT record_version FROM payment_requests WHERE id = %s", request_id)[0][0]
    )


def read_publication(world: dict[str, Any], request_id: uuid.UUID) -> Any:
    return world["client"].get(
        f"/api/v1/me/trader/payment-requests/{request_id}/publication"
    )


def acknowledge(world: dict[str, Any], request_id: uuid.UUID, **overrides: Any) -> Any:
    client = world["client"]
    version = overrides.pop("version", None) or request_version(world, request_id)
    return client.post(
        f"/api/v1/me/trader/payment-requests/{request_id}/acknowledge-result",
        json={},
        headers={
            **csrf(world),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": overrides.pop("key", None) or str(uuid.uuid4()),
        },
    )


def dispute(world: dict[str, Any], request_id: uuid.UUID, **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "reason_code": "beneficiary_did_not_receive",
        "description": "The recipient reports that payment has not arrived.",
    }
    body.update({k: v for k, v in overrides.items() if k not in {"version", "key"}})
    version = overrides.get("version") or request_version(world, request_id)
    return client.post(
        f"/api/v1/me/trader/payment-requests/{request_id}/dispute-result",
        json=body,
        headers={
            **csrf(world),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": overrides.get("key") or str(uuid.uuid4()),
        },
    )


def financial_snapshot(world: dict[str, Any], case: dict[str, Any]) -> tuple[Any, Any]:
    """Every column of the attempt and the publication, as JSON.

    `row_to_json` rather than a column list, for the reason M6's supersession test gives: a listed
    set of columns cannot notice the one somebody adds later, and the claim here is that *nothing*
    financial moved.
    """

    attempt = rows(
        world,
        "SELECT row_to_json(t) FROM (SELECT * FROM payment_attempts WHERE id = %s) t",
        case["attempt_id"],
    )[0][0]
    publication = rows(
        world,
        "SELECT row_to_json(t) FROM "
        "(SELECT * FROM payment_result_publications WHERE id = %s) t",
        case["publication_id"],
    )[0][0]
    return attempt, publication


def test_a_trader_reads_their_own_active_publication(world: dict[str, Any]) -> None:
    """§20.4. The payload, and the two response timestamps a screen needs."""

    case = a_published_request(world)
    sign_in_trader(world, OWNER_PHONE)

    response = read_publication(world, case["request_id"])
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["publication_version"] == 1
    assert body["status"] == "active"
    assert body["request_status"] == "result_published"
    assert body["summary_payload"]["amount_irr"] == "600000000"
    assert body["acknowledged_at"] is None
    assert body["disputed_at"] is None


def test_the_trader_response_hides_who_published_it(world: dict[str, Any]) -> None:
    """The centre's record of its own act is not the trader's business.

    Asserted over the response keys rather than by looking for a value: a field that is present and
    null today is a field somebody fills in later.
    """

    case = a_published_request(world)
    sign_in_trader(world, OWNER_PHONE)

    body = read_publication(world, case["request_id"]).json()
    for hidden in ("published_by_admin_user_id", "supersedes_publication_id", "correction_reason"):
        assert hidden not in body, f"{hidden} reached a trader response"


def test_another_trader_gets_404_and_not_403(world: dict[str, Any]) -> None:
    """`API-PUBLICATION-001`. §17 `:1185`, and the code is the assertion.

    A 403 would confirm the publication exists. Over request identifiers that is an enumeration
    oracle, which is why `app/security/ownership.py` makes not-mine and not-existing answer alike.
    """

    case = a_published_request(world, trader_key="owner")
    sign_in_trader(world, OTHER_PHONE)

    response = read_publication(world, case["request_id"])
    assert response.status_code == 404, (
        f"a second trader received {response.status_code}. Anything other than 404 tells them the "
        "publication exists."
    )

    assert dispute(world, case["request_id"]).status_code == 404
    assert acknowledge(world, case["request_id"]).status_code == 404


def test_a_trader_acknowledges_and_nothing_financial_moves(world: dict[str, Any]) -> None:
    """`SVC-ACKNOWLEDGE-001`. §20.5, and the same read-back as the dispute test.

    Agreeing is the safer of the two actions and gets the same assertion, because "the safe one"
    is exactly where a convenience write gets added.
    """

    case = a_published_request(world)
    before = financial_snapshot(world, case)
    sign_in_trader(world, OWNER_PHONE)

    response = acknowledge(world, case["request_id"])
    assert response.status_code == 200, response.text
    assert response.json()["request_status"] == "trader_acknowledged"
    assert response.json()["acknowledged_at"] is not None

    assert financial_snapshot(world, case) == before, (
        "acknowledging a result changed an attempt or a publication row"
    )


def test_a_dispute_reverses_no_bank_fact(world: dict[str, Any]) -> None:
    """`SVC-DISPUTE-001`. Doc 05 `:1942`: "does not automatically reverse bank facts."

    **The test that would pass against almost anything if it only read the status.** Every column
    of the attempt and the publication is compared, so an implementation that helpfully marked the
    attempt unpaid — the intuitive response to "the money did not arrive" — fails here.
    """

    case = a_published_request(world)
    before = financial_snapshot(world, case)
    sign_in_trader(world, OWNER_PHONE)

    response = dispute(world, case["request_id"])
    assert response.status_code == 200, response.text
    assert response.json()["request_status"] == "trader_disputed"

    after = financial_snapshot(world, case)
    assert after == before, (
        "a dispute changed a bank fact. The trader's claim opens a review; it does not decide it."
    )


def test_a_dispute_opens_a_task_naming_the_exact_publication_version(
    world: dict[str, Any],
) -> None:
    """§17 `:1185`: "dispute references the exact publication version", and §20.6's task.

    The version goes in `entity_record_version` rather than into the title alone, so a queue can
    answer "which version is being disputed" with a query. `20260901_0032` is what lets the entity
    be the publication rather than an attempt.
    """

    case = a_published_request(world)
    sign_in_trader(world, OWNER_PHONE)
    assert dispute(world, case["request_id"]).status_code == 200

    task = rows(
        world,
        "SELECT task_type, entity_type, entity_id, entity_record_version, priority, status, "
        "description FROM manual_review_tasks WHERE entity_id = %s",
        case["publication_id"],
    )
    assert len(task) == 1, f"expected one dispute task, got {task}"
    assert task[0][0] == "payment_result_discrepancy"
    assert task[0][1] == "payment_result_publication"
    assert uuid.UUID(str(task[0][2])) == case["publication_id"]
    assert task[0][3] == 1, (
        "the task does not carry the publication version, so nothing can answer which version the "
        "trader disputed"
    )
    assert task[0][5] == "open"
    assert "has not arrived" in task[0][6]


def test_resolving_a_dispute_keeps_the_publication_version(world: dict[str, Any]) -> None:
    """The trap in `resolve_task`, which sets `entity_record_version` from the subject.

    That behaviour is right for a privacy review — it records the version somebody judged — and
    would have silently erased the dispute's reference, because a publication was not a case the
    function knew about. It is now, and the number is the same either way because the row is
    immutable.
    """

    case = a_published_request(world)
    sign_in_trader(world, OWNER_PHONE)
    assert dispute(world, case["request_id"]).status_code == 200

    task_id = rows(
        world,
        "SELECT id FROM manual_review_tasks WHERE entity_id = %s",
        case["publication_id"],
    )[0][0]

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE manual_review_tasks SET status = 'resolved', resolved_at = now(), "
            "resolved_by_admin_user_id = %s, resolution_code = 'no_action_required', "
            "entity_record_version = NULL WHERE id = %s",
            (admin_id(world, "trader_pub_accountant"), task_id),
        )
        connection.commit()

    # The direct write above is what `resolve_task` would have produced before this slice taught
    # `_subject_version` about publications. Re-deriving it must give the version back.
    #
    # `owner_url` is already psycopg's plain form — `conftest.py` strips the `+psycopg` prefix for
    # the driver's benefit — so SQLAlchemy needs it put back or it reaches for psycopg2, which is
    # not installed. The first version of this test did exactly that.
    from app.commands.manual_review_task import _subject_version
    from app.db.models.manual_review_task import ManualReviewTask
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(
        world["owner_url"].replace("postgresql://", "postgresql+psycopg://", 1)
    )
    try:
        with Session(engine) as session:
            task = session.get(ManualReviewTask, uuid.UUID(str(task_id)))
            assert task is not None
            assert _subject_version(session, task) == 1, (
                "resolving a dispute would leave `entity_record_version` empty, and §17 `:1185`'s "
                "reference to the exact publication version would vanish at the moment somebody "
                "acted on it"
            )
    finally:
        engine.dispose()


def a_share_file(world: dict[str, Any], case: dict[str, Any]) -> uuid.UUID:
    """Attach a rendered card to the case's publication, with its bytes in storage.

    Written directly rather than by publishing through the API: slice 5's publish path renders the
    card and slice 5's tests prove it. What this module owns is who may *download* one.
    """

    import io

    from app.exports.share_card import render_share_card

    file_id = uuid.uuid4()
    card = render_share_card({"request_number": "PR-SHARE", "attempts": []}, None)
    key = f"cards/{file_id}"
    world["client"].app.state.runtime.storage.write(key, io.BytesIO(card))

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, 'result.png', 'image/png', %s, %s, "
            "'incoming_payment_receipt', 'trader_visible_after_publication', 'available', "
            "'clean', 'system_worker', 'derived', '{}')",
            (file_id, key, len(card), "f" * 64),
        )
        connection.execute(
            "UPDATE payment_result_publications SET share_file_id = %s WHERE id = %s",
            (file_id, case["publication_id"]),
        )
        connection.commit()
    return file_id


def test_a_trader_downloads_their_own_result_card(world: dict[str, Any]) -> None:
    """`FILE-PUBLICATION-002`, doc 05 §20.4's second route.

    Asserted on the PNG magic number rather than only on the content type: a route returning an
    empty body with the right header would satisfy the header alone.
    """

    case = a_published_request(world)
    a_share_file(world, case)
    sign_in_trader(world, OWNER_PHONE)

    response = world["client"].get(
        f"/api/v1/me/trader/publications/{case['publication_id']}/share-file"
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_another_trader_cannot_download_the_share_file(world: dict[str, Any]) -> None:
    """`API-PUBLICATION-001` through a **publication** id rather than a request id.

    A different chain from the read route's — publication → request → owner — and therefore a
    separate way to get it wrong, which is why it has its own test rather than sharing one.
    """

    case = a_published_request(world, trader_key="owner")
    a_share_file(world, case)
    sign_in_trader(world, OTHER_PHONE)

    response = world["client"].get(
        f"/api/v1/me/trader/publications/{case['publication_id']}/share-file"
    )
    assert response.status_code == 404, (
        f"a second trader received {response.status_code}. Anything but 404 confirms the card "
        "exists, which over publication identifiers is an enumeration oracle."
    )


def test_a_publication_with_no_card_answers_404(world: dict[str, Any]) -> None:
    """`share_file_id` is nullable — a publication citing no evidence gets no card.

    404 rather than a success with no bytes, which a client would write to disk as an empty file.
    """

    case = a_published_request(world)
    sign_in_trader(world, OWNER_PHONE)

    response = world["client"].get(
        f"/api/v1/me/trader/publications/{case['publication_id']}/share-file"
    )
    assert response.status_code == 404, response.text


def test_a_trader_cannot_respond_before_a_result_is_published(
    world: dict[str, Any],
) -> None:
    """`06_Workflows_and_State_Machines.md:602`. Both arrows leave `result_published`."""

    case = a_published_request(world)
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_requests SET status = 'paid' WHERE id = %s", (case["request_id"],)
        )
        connection.commit()

    sign_in_trader(world, OWNER_PHONE)
    response = dispute(world, case["request_id"])
    assert response.status_code == 400, response.text
    assert "result_published" in response.text


def test_acknowledging_twice_is_refused_but_a_replay_is_not(world: dict[str, Any]) -> None:
    """Two different situations that must not be conflated.

    The same `Idempotency-Key` means "my network dropped your answer" and returns it. A *new* key
    against an already-acknowledged request means the caller does not know what they are looking
    at, and gets told.
    """

    case = a_published_request(world)
    sign_in_trader(world, OWNER_PHONE)

    key = str(uuid.uuid4())
    first = acknowledge(world, case["request_id"], key=key)
    assert first.status_code == 200, first.text

    replay = acknowledge(world, case["request_id"], key=key)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"]

    fresh = acknowledge(world, case["request_id"])
    assert fresh.status_code == 400, fresh.text


def test_a_stale_if_match_refuses_a_trader_response(world: dict[str, Any]) -> None:
    """`current_publication_identity_revalidated`, from the catalogue's own concurrency note.

    The situation it exists for: a correction replaces the result while the trader is reading it.
    Publishing N+1 moves the request, so the version the trader is holding is no longer current.
    """

    case = a_published_request(world)
    sign_in_trader(world, OWNER_PHONE)

    stale = request_version(world, case["request_id"])
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_requests SET record_version = record_version + 1 WHERE id = %s",
            (case["request_id"],),
        )
        connection.commit()

    response = dispute(world, case["request_id"], version=stale)
    assert response.status_code == 412, response.text


def test_both_trader_responses_are_audited_with_no_outbox_event(
    world: dict[str, Any],
) -> None:
    """`AUD-PUBLICATION-001`. `audit_outbox_catalog.yaml:48-49`, both halves.

    The absence is asserted as well as the presence: the catalogue lists no event for either, and
    nothing outside this platform acts on a trader's opinion of a result.
    """

    acknowledged = a_published_request(world)
    disputed = a_published_request(world)
    sign_in_trader(world, OWNER_PHONE)

    assert acknowledge(world, acknowledged["request_id"]).status_code == 200
    assert dispute(world, disputed["request_id"]).status_code == 200

    for request_id, action in (
        (acknowledged["request_id"], ACKNOWLEDGE_ACTION),
        (disputed["request_id"], DISPUTE_ACTION),
    ):
        entries = rows(
            world,
            "SELECT action, entity_type, new_values FROM audit_logs "
            "WHERE entity_id = %s AND action = %s",
            request_id,
            action,
        )
        assert len(entries) == 1, f"expected one {action} row, got {entries}"
        assert entries[0][1] == "payment_request"
        assert entries[0][2]["publication_version"] == 1

    events = rows(
        world,
        "SELECT event_type FROM outbox_events WHERE aggregate_id IN (%s, %s)",
        acknowledged["request_id"],
        disputed["request_id"],
    )
    assert events == [], (
        f"a trader response enqueued {events}. `audit_outbox_catalog.yaml` lists no event for "
        "either action, and an event nobody consumes is a second delivery path for one fact."
    )


def test_a_dispute_requires_a_reason_and_a_description(world: dict[str, Any]) -> None:
    """Both required by the schema *and* by the command.

    The schema gives a client a 422 naming the field; the command gives the same refusal to any
    caller that does not come through it. Slice 2 records the reason for keeping both.
    """

    case = a_published_request(world)
    sign_in_trader(world, OWNER_PHONE)

    assert dispute(world, case["request_id"], reason_code="").status_code == 422
    assert dispute(world, case["request_id"], description="").status_code == 422
    assert publications_disputed(world, case["request_id"]) is None


def test_a_dispute_body_cannot_name_a_file(world: dict[str, Any]) -> None:
    """`attachment_file_ids` is in document 05 and deliberately not in the model.

    Accepting a file id nothing checks the ownership of is the IDOR case
    `14_Testing_QA_Acceptance.md:1274` names, arriving through a field that looks helpful.
    `extra="forbid"` turns it into a 422 rather than a silently ignored field.
    """

    case = a_published_request(world)
    sign_in_trader(world, OWNER_PHONE)

    response = dispute(world, case["request_id"], attachment_file_ids=[str(uuid.uuid4())])
    assert response.status_code == 422, response.text


def publications_disputed(world: dict[str, Any], request_id: uuid.UUID) -> Any:
    return rows(
        world, "SELECT trader_disputed_at FROM payment_requests WHERE id = %s", request_id
    )[0][0]
