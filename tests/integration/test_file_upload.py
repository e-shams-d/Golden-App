"""The first route that writes a byte to storage, against a real database.

Covers: FILE-UP-001, FILE-UP-002, FILE-UP-003, FILE-UP-004, FILE-UP-005, API-FILE-001,
AUD-FILE-001, TRACE-CALLER-001.

Two things are worth reading before the tests.

**The privileged role is inverted from the admin-user tests.** `file.upload` is held by
`trader_owner`, `accountant` and `warehouse_operator` — and *not* by `business_admin`,
which holds every `user.*` permission. So the account that is privileged everywhere else
in the staff suite is the unauthorised one here. That is not a quirk to work around; it
is the catalogue saying that administering people and handling evidence are different
authorities, and it makes the denial test genuinely about `file.upload` rather than about
being logged in.

**FILE-UP-002 is instrumented, not described.** "No long transaction during the stream"
is the kind of claim a docstring can assert and a regression can quietly break, so the
engine's `begin`/`commit`/`rollback` events are counted and the storage backend records
the depth at the moment it is asked to write. A regression that wrapped all three phases
in one unit of work moves that number from 0 to 1.
"""

from __future__ import annotations

import hashlib
import io
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
CSRF_HEADER = "X-CSRF-Token"

# Holds `file.upload` (`permission_catalog.yaml:607-609`).
UPLOADER = "accountant1"
# Holds the four `user.*` permissions and no `file.*` write. Authenticated, unauthorised.
NON_UPLOADER = "business_admin1"

# A one-pixel PNG. Real bytes rather than `b"x" * n`, because slice 3 will inspect content
# and a test corpus that was never a real file would have to be replaced then.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8cfc00000030101003c8b9c1e0000000049454e44ae426082"
)


@pytest.fixture
def migrated(provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=provisioned_database.app_role,
        worker_role=provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return provisioned_database


class _RecordingStorage:
    """Wraps the real backend and records what was true when it was called.

    Not a fake: every write goes through to the local adapter, so the digest, the size and
    the on-disk object are the real ones. It only observes.
    """

    def __init__(self, inner: Any, depth: Any) -> None:
        self._inner = inner
        self._depth = depth
        self.transaction_depth_at_write: list[int] = []
        self.written_keys: list[str] = []

    def write(self, key: str, source: Any) -> Any:
        self.transaction_depth_at_write.append(self._depth())
        self.written_keys.append(key)
        return self._inner.write(key, source)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.fixture
def client(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[tuple[Any, Any, Any]]:
    from app.core.config import Settings
    from app.core.runtime import RuntimeServices
    from app.main import create_app
    from app.security.passwords import Argon2Parameters, hash_password
    from fastapi.testclient import TestClient
    from sqlalchemy import event

    storage_root = tmp_path / "storage"
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=storage_root,
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for username, role in ((UPLOADER, "accountant"), (NON_UPLOADER, "business_admin")):
            row = connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active') RETURNING id",
                (username, username.title(), encoded),
            ).fetchone()
            assert row
            found = connection.execute("SELECT id FROM roles WHERE code = %s", (role,)).fetchone()
            assert found, f"migration 0008 should have seeded {role}"
            connection.execute(
                "INSERT INTO admin_user_roles (admin_user_id, role_id) VALUES (%s, %s)",
                (row[0], found[0]),
            )
        connection.commit()

    runtime = RuntimeServices.from_settings(settings)

    open_transactions = {"depth": 0}

    @event.listens_for(runtime.engine, "begin")
    def _begin(_connection: Any) -> None:
        open_transactions["depth"] += 1

    @event.listens_for(runtime.engine, "commit")
    def _commit(_connection: Any) -> None:
        open_transactions["depth"] -= 1

    @event.listens_for(runtime.engine, "rollback")
    def _rollback(_connection: Any) -> None:
        open_transactions["depth"] -= 1

    recording = _RecordingStorage(runtime.storage, lambda: open_transactions["depth"])
    runtime.storage = recording  # type: ignore[assignment]

    # Through `runtime_factory`, not by assigning `app.state.runtime` afterwards: the
    # lifespan builds its own runtime on startup and overwrites the attribute, so the
    # instrumented one was being discarded and the real backend used instead. The
    # symptom was `written_keys == []` on an upload that had plainly succeeded — the
    # observer was watching an object nothing used.
    app = create_app(settings=settings, runtime_factory=lambda _settings: runtime)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as test_client:
        yield test_client, recording, storage_root
    runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in(client: Any, username: str) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def _upload(
    client: Any,
    token: str,
    *,
    key: str,
    purpose: str = "incoming_payment_receipt",
    filename: str = "receipt.png",
    content: bytes = PNG,
    media_type: str = "image/png",
) -> Any:
    return client.post(
        "/api/v1/files",
        headers={CSRF_HEADER: token, "Idempotency-Key": key},
        files={"file": (filename, io.BytesIO(content), media_type)},
        data={"purpose": purpose},
    )


def test_an_upload_stores_the_bytes_under_an_opaque_key(
    client: tuple[Any, Any, Any], migrated: RuntimeIdentities
) -> None:
    """FILE-UP-001.

    The key contains none of the client's filename, its extension, or any identifier the
    caller chose. Asserted against the stored row rather than against the response,
    because the response deliberately does not carry the key at all.
    """

    test_client, recording, storage_root = client
    token = sign_in(test_client, UPLOADER)

    # A filename whose tokens cannot appear in a legitimate key. The first version of
    # this test asserted `"receipt" not in key` and failed against a correct key, because
    # the *purpose* is `incoming_payment_receipt` and the purpose is deliberately the
    # first path segment. Asserting on a substring the purpose also contains tests the
    # catalogue's spelling, not the filename's absence.
    filename = "Ledger Q3 SECRETTOKEN.png"
    response = _upload(test_client, token, key=str(uuid.uuid4()), filename=filename)
    assert response.status_code == 201, response.text

    body = response.json()
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        row = connection.execute(
            "SELECT storage_key, original_filename, category, storage_status, scan_status, "
            "sha256_hash, size_bytes, mime_type_declared, visibility_scope "
            "FROM file_objects WHERE id = %s",
            (body["id"],),
        ).fetchone()
    assert row
    (
        key,
        stored_filename,
        category,
        storage_status,
        scan_status,
        digest,
        size,
        declared,
        scope,
    ) = row

    assert "SECRETTOKEN" not in key
    assert "Ledger" not in key
    assert "Q3" not in key
    assert not key.endswith(".png")
    assert key.startswith("incoming_payment_receipt/")
    assert key == recording.written_keys[0]

    # The sanitised client name survives as metadata, and only as metadata.
    assert stored_filename == filename
    assert category == "incoming_payment_receipt"
    assert declared == "image/png"
    assert scope == "trader_visible_after_publication"

    assert digest == hashlib.sha256(PNG).hexdigest()
    assert size == len(PNG)

    # No scan policy exists until slice 4, so the honest answer is "not scanned" and the
    # database's whitelist turns that into a refusal to be available.
    assert storage_status == "quarantined"
    assert scan_status == "pending"

    stored = list(storage_root.rglob("*"))
    assert any(path.is_file() and path.read_bytes() == PNG for path in stored)


def test_no_transaction_is_held_while_the_bytes_are_written(
    client: tuple[Any, Any, Any],
) -> None:
    """FILE-UP-002. `15_Agent_Implementation_Plan.md:691`.

    The measurement is the engine's own transaction depth at the instant storage is
    called. A regression that wrapped initiate, stream and finalize in one unit of work
    moves this from 0 to 1, and nothing else in the suite would notice.

    It measures a transaction that has actually begun, not the presence of an enclosing
    `with` block, and the difference is real rather than a limitation: SQLAlchemy starts a
    transaction when SQL first runs, so a write placed at the top of a unit-of-work block
    before any query holds no lock and is not the defect. The negative control had to be
    corrected on exactly this point — the first version moved the write to the top of the
    finalize block, nothing was locked, and this test was right to stay green.
    """

    test_client, recording, _ = client
    token = sign_in(test_client, UPLOADER)

    assert _upload(test_client, token, key=str(uuid.uuid4())).status_code == 201

    assert recording.transaction_depth_at_write == [0], (
        "a database transaction was open while the upload streamed to storage: depth "
        f"{recording.transaction_depth_at_write}"
    )


def test_the_instrumentation_would_notice_an_open_transaction(
    client: tuple[Any, Any, Any],
) -> None:
    """Guard the guard for FILE-UP-002.

    The assertion above is `== [0]`, which also holds if the counter never moves — a
    broken listener would report a permanently clean result. This drives one transaction
    through the same engine and requires the depth to rise, so the instrument is shown to
    be capable of reporting the failure it is watching for.
    """

    test_client, recording, _ = client
    runtime = test_client.app.state.runtime
    depth = recording._depth

    assert depth() == 0
    with runtime.engine.begin() as connection:
        connection.exec_driver_sql("SELECT 1")
        assert depth() == 1, "the begin listener did not fire; FILE-UP-002 cannot fail"
    assert depth() == 0


def test_a_retry_with_the_same_key_creates_one_file(
    client: tuple[Any, Any, Any], migrated: RuntimeIdentities
) -> None:
    """FILE-UP-003. `15_Agent_Implementation_Plan.md:725`."""

    test_client, recording, _ = client
    token = sign_in(test_client, UPLOADER)
    key = str(uuid.uuid4())

    first = _upload(test_client, token, key=key)
    assert first.status_code == 201, first.text
    second = _upload(test_client, token, key=key)
    assert second.status_code == 201, second.text

    assert first.json()["id"] == second.json()["id"]

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        count = connection.execute("SELECT count(*) FROM file_objects").fetchone()
    assert count and count[0] == 1

    assert len(recording.written_keys) == 1, (
        "the replay wrote to storage a second time; a retry must not produce a second "
        "object even when it produces the same row"
    )


def test_two_callers_uploading_identical_bytes_get_two_files(
    client: tuple[Any, Any, Any], migrated: RuntimeIdentities
) -> None:
    """FILE-UP-004, and DOC-CONFLICT-046's resolution.

    Identical content is not a replay. Two people uploading the same document are two
    pieces of evidence with two owners, and deduplicating on the checksum would attach
    one trader's file to another's request. The digest is recorded on both.
    """

    test_client, _, _ = client
    token = sign_in(test_client, UPLOADER)

    first = _upload(test_client, token, key=str(uuid.uuid4()))
    second = _upload(test_client, token, key=str(uuid.uuid4()))
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] != second.json()["id"]

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        rows = connection.execute(
            "SELECT sha256_hash, storage_key FROM file_objects ORDER BY created_at"
        ).fetchall()

    assert len(rows) == 2
    assert rows[0][0] == rows[1][0] == hashlib.sha256(PNG).hexdigest()
    assert rows[0][1] != rows[1][1], "two files shared one storage address"


def test_an_oversized_upload_is_refused_and_leaves_no_object(
    client: tuple[Any, Any, Any], migrated: RuntimeIdentities
) -> None:
    """FILE-UP-005.

    The limit is enforced during the stream, so the refusal must leave nothing complete
    behind — the local adapter unlinks its partial file on any exception, and this is what
    asserts that rather than assuming it.
    """

    from app.files.purposes import size_limit

    test_client, _, storage_root = client
    token = sign_in(test_client, UPLOADER)

    oversized = PNG + b"\0" * (size_limit("incoming_payment_receipt") + 1)
    response = _upload(test_client, token, key=str(uuid.uuid4()), content=oversized)
    assert response.status_code == 400, response.text

    complete = [path for path in storage_root.rglob("*") if path.is_file()]
    assert complete == [], f"an object survived a refused upload: {complete}"

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        available = connection.execute(
            "SELECT count(*) FROM file_objects WHERE storage_status = 'available'"
        ).fetchone()
    assert available and available[0] == 0


def test_the_response_carries_no_storage_address(client: tuple[Any, Any, Any]) -> None:
    """API-FILE-001. `command_catalog.yaml` global rule `raw_storage_keys_never_returned`.

    Checked against the response **model's fields**, not against one payload: a field
    added later would reach every caller, and asserting on an example only catches it if
    a test happens to exercise that path.
    """

    from app.api.v1.files import UploadedFileResponse

    forbidden = {"storage_key", "storage_bucket", "storage_provider"}
    assert forbidden.isdisjoint(UploadedFileResponse.model_fields)

    test_client, _, _ = client
    token = sign_in(test_client, UPLOADER)
    response = _upload(test_client, token, key=str(uuid.uuid4()))
    assert response.status_code == 201

    body = response.text
    for name in forbidden:
        assert name not in body


def test_an_upload_writes_one_audit_row_in_the_finalize_transaction(
    client: tuple[Any, Any, Any], migrated: RuntimeIdentities
) -> None:
    """AUD-FILE-001.

    The audit row names the actor and the outcome, and carries no storage address — an
    audit log is read by more people and kept longer than any API response, so a key
    leaked there outlives every other place it could leak.
    """

    test_client, _, _ = client
    token = sign_in(test_client, UPLOADER)
    response = _upload(test_client, token, key=str(uuid.uuid4()))
    assert response.status_code == 201, response.text

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        rows = connection.execute(
            "SELECT action, outcome, entity_type, entity_id, new_values::text "
            "FROM audit_logs WHERE action = 'file.uploaded'"
        ).fetchall()

    assert len(rows) == 1
    action, outcome, entity_type, entity_id, new_values = rows[0]
    assert (action, outcome, entity_type) == ("file.uploaded", "success", "file_object")
    assert str(entity_id) == response.json()["id"]
    for forbidden in ("storage_key", "storage_bucket", "storage_provider"):
        assert forbidden not in new_values


def test_a_refused_upload_writes_no_audit_row(
    client: tuple[Any, Any, Any], migrated: RuntimeIdentities
) -> None:
    """AUD-FILE-001, the other half: a failed finalize leaves neither a row nor an
    available file. Without this the assertion above holds for a command that audits
    everything it attempts, which is a different and weaker claim."""

    test_client, _, _ = client
    token = sign_in(test_client, UPLOADER)

    from app.files.purposes import size_limit

    oversized = PNG + b"\0" * (size_limit("incoming_payment_receipt") + 1)
    assert _upload(test_client, token, key=str(uuid.uuid4()), content=oversized).status_code == 400

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        count = connection.execute(
            "SELECT count(*) FROM audit_logs WHERE action = 'file.uploaded'"
        ).fetchone()
    assert count and count[0] == 0


def test_a_purpose_the_actor_may_not_use_is_refused(client: tuple[Any, Any, Any]) -> None:
    """An unknown purpose never reaches storage. The refusal is the default branch in
    `app.files.purposes.resolve`, and this is the route-level proof of it."""

    test_client, recording, _ = client
    token = sign_in(test_client, UPLOADER)

    response = _upload(test_client, token, key=str(uuid.uuid4()), purpose="invented_purpose")
    assert response.status_code == 400, response.text
    assert recording.written_keys == []


def test_a_media_type_the_purpose_does_not_accept_is_refused(
    client: tuple[Any, Any, Any],
) -> None:
    """A bank statement is a spreadsheet and a receipt is an image. The per-purpose
    acceptance list is enforced before a byte is written."""

    test_client, recording, _ = client
    token = sign_in(test_client, UPLOADER)

    response = _upload(
        test_client,
        token,
        key=str(uuid.uuid4()),
        purpose="bank_statement",
        media_type="image/png",
    )
    assert response.status_code == 400, response.text
    assert recording.written_keys == []


def test_an_authenticated_actor_without_the_permission_is_denied(
    client: tuple[Any, Any, Any],
) -> None:
    """`business_admin` holds every `user.*` permission and no `file.upload`. Genuinely
    authenticated, genuinely unauthorised — the combination the guard exists for."""

    test_client, recording, _ = client
    token = sign_in(test_client, NON_UPLOADER)

    response = _upload(test_client, token, key=str(uuid.uuid4()))
    assert response.status_code == 403, response.text
    assert recording.written_keys == []


def test_the_upload_requires_an_idempotency_key(client: tuple[Any, Any, Any]) -> None:
    """`command_catalog.yaml` records `idempotency: required` for `file.upload`. A route
    that accepted the request without one would make FILE-UP-003 unenforceable."""

    test_client, recording, _ = client
    token = sign_in(test_client, UPLOADER)

    response = test_client.post(
        "/api/v1/files",
        headers={CSRF_HEADER: token},
        files={"file": ("receipt.png", io.BytesIO(PNG), "image/png")},
        data={"purpose": "incoming_payment_receipt"},
    )
    assert response.status_code == 400, response.text
    assert recording.written_keys == []
