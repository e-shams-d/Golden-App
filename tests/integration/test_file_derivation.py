"""Derived files and preview dispatch, against a real database.

Covers: FILE-DERIV-001, FILE-DERIV-002, FILE-DERIV-003, JOB-PREVIEW-001, JOB-PREVIEW-002.

Every claim here is about atomicity or about a row existing, so all of it needs a
database. The two halves are related by intent: a preview is dispatched now and rendered
in M8, and when the renderer arrives it will record its output through `record_derivation`
— so the derivation rules are proved before anything depends on them, rather than after.
"""

from __future__ import annotations

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
ACCOUNTANT = "accountant1"

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8cfc00000030101003c8b9c1e0000000049454e44ae426082"
)
CSV = b"date,amount\n2026-08-16,1000\n"

# The derivative's bytes must differ from the source's. They were identical in the first
# version of this file, which made `source_hash` and the derivative's own digest the same
# value — so the assertion that the row records the *source's* hash could not fail, and a
# sabotage swapping one for the other passed. A fixture that makes two different things
# equal is a fixture that hides the difference it was written to check.
DERIVED_PNG = PNG + b"\x00"


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


@pytest.fixture
def world(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[dict[str, Any]]:
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
        local_storage_root=tmp_path / "storage",
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret=None,
        file_scan_policy="development_bypass",
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        row = connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES (%s, 'Accountant', %s, 'active') RETURNING id",
            (ACCOUNTANT, encoded),
        ).fetchone()
        assert row
        found = connection.execute("SELECT id FROM roles WHERE code = 'accountant'").fetchone()
        assert found
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) VALUES (%s, %s)",
            (row[0], found[0]),
        )
        connection.commit()

    runtime = RuntimeServices.from_settings(settings)
    app = create_app(settings=settings, runtime_factory=lambda _settings: runtime)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as client:
        yield {"client": client, "runtime": runtime, "url": migrated.owner_url}
    runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in(client: Any) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": ACCOUNTANT, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def upload(
    client: Any,
    token: str,
    *,
    content: bytes = PNG,
    media_type: str = "image/png",
    purpose: str = "incoming_payment_receipt",
    filename: str = "receipt.png",
) -> str:
    response = client.post(
        "/api/v1/files",
        headers={CSRF_HEADER: token, "Idempotency-Key": str(uuid.uuid4())},
        files={"file": (filename, io.BytesIO(content), media_type)},
        data={"purpose": purpose},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _request(source_id: str, *, renderer: str = "preview-1.0", page: int = 1) -> Any:
    from app.files.derivation import DerivationRequest

    return DerivationRequest(
        source_file_id=uuid.UUID(source_id),
        derivation_type="preview",
        renderer_version=renderer,
        parameters={"page": page},
        media_type="image/png",
        filename="preview-1.png",
        body=io.BytesIO(DERIVED_PNG),
    )


def _counts(url: str) -> tuple[int, int]:
    with psycopg.connect(_psycopg(url)) as connection:
        derived = connection.execute(
            "SELECT count(*) FROM file_objects WHERE original_or_derived_relation = 'derived'"
        ).fetchone()
        derivations = connection.execute("SELECT count(*) FROM file_derivations").fetchone()
    assert derived and derivations
    return derived[0], derivations[0]


def test_a_derived_file_and_its_derivation_commit_together(world: dict[str, Any]) -> None:
    """FILE-DERIV-001."""

    from app.core.time import utc_now
    from app.files.derivation import record_derivation

    client, runtime, url = world["client"], world["runtime"], world["url"]
    source_id = upload(client, sign_in(client))

    with runtime.uow_factory() as uow:
        result = record_derivation(
            _request(source_id), uow=uow, storage=runtime.storage, moment=utc_now()
        )
        uow.commit()

    assert _counts(url) == (1, 1)

    with psycopg.connect(_psycopg(url)) as connection:
        row = connection.execute(
            "SELECT source_file_id, derived_file_id, derivation_type, renderer_version, "
            "source_hash FROM file_derivations WHERE id = %s",
            (result.derivation_id,),
        ).fetchone()
        source_hash = connection.execute(
            "SELECT sha256_hash FROM file_objects WHERE id = %s", (source_id,)
        ).fetchone()
    assert row and source_hash
    assert str(row[0]) == source_id
    assert str(row[1]) == str(result.derived_file_id)
    assert row[2] == "preview"
    assert row[3] == "preview-1.0"
    # The source's digest at the moment of derivation, which is what says later whether
    # the derivative still corresponds to its source. Asserted as *not* the derivative's
    # own digest as well, because the two were equal in the first version of this fixture
    # and the distinction is the entire content of this column.
    assert row[4] == source_hash[0]
    assert row[4] != result.sha256


def test_a_failure_after_the_derived_file_leaves_neither_row(world: dict[str, Any]) -> None:
    """FILE-DERIV-001's other half, and the one that matters.

    A derived `file_object` without a `file_derivations` row is an artifact nobody can
    account for: it looks like evidence and nothing says what produced it. The rollback
    must take both.
    """

    from app.files.derivation import record_derivation

    client, runtime, url = world["client"], world["runtime"], world["url"]
    source_id = upload(client, sign_in(client))
    from app.core.time import utc_now

    with pytest.raises(RuntimeError, match="renderer exploded"), runtime.uow_factory() as uow:
        record_derivation(
            _request(source_id), uow=uow, storage=runtime.storage, moment=utc_now()
        )
        raise RuntimeError("renderer exploded")

    assert _counts(url) == (0, 0)


def test_the_reconciliation_check_agrees_with_the_writer(world: dict[str, Any]) -> None:
    """FILE-DERIV-002.

    The writer and the check are proved against each other rather than separately: after
    a successful derivation the check finds nothing, and after a deliberately partial one
    it finds the orphan. Either alone could be wrong in the same direction.
    """

    from app.core.time import utc_now
    from app.files.derivation import record_derivation
    from app.storage.reconciliation import derivatives_without_a_derivation

    client, runtime, url = world["client"], world["runtime"], world["url"]
    source_id = upload(client, sign_in(client))

    with runtime.uow_factory() as uow:
        record_derivation(_request(source_id), uow=uow, storage=runtime.storage, moment=utc_now())
        uow.commit()

    # The reconciliation checks take a SQLAlchemy connection, not a psycopg one — they
    # are written against the same engine the application uses.
    with runtime.engine.connect() as connection:
        assert derivatives_without_a_derivation(connection) == []

    # A derived file with no derivation row — written directly, because the command layer
    # will not produce one and that is the point.
    with psycopg.connect(_psycopg(url)) as raw:
        raw.execute(
            "INSERT INTO file_objects (storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation) VALUES ('local', 'private', %s, 'orphan.png', "
            "'image/png', 3, %s, 'misc_internal', 'internal_only', 'available', 'clean', "
            "'system_worker', 'derived')",
            (f"preview/2026/08/16/{uuid.uuid4().hex}", "d" * 64),
        )
        raw.commit()

    with runtime.engine.connect() as connection:
        findings = derivatives_without_a_derivation(connection)
    assert len(findings) == 1


def test_two_renderer_versions_are_two_derivations_not_a_conflict(
    world: dict[str, Any],
) -> None:
    """FILE-DERIV-003.

    Two renderers can agree on the parameters and disagree on the output, so a version
    change is a new derivation. The unique constraint includes the renderer version for
    exactly this reason, and asserting it means a future "cleanup" that drops it from the
    key fails here rather than silently collapsing two different pictures into one.
    """

    from app.core.time import utc_now
    from app.files.derivation import record_derivation

    client, runtime, url = world["client"], world["runtime"], world["url"]
    source_id = upload(client, sign_in(client))

    for renderer in ("preview-1.0", "preview-2.0"):
        with runtime.uow_factory() as uow:
            record_derivation(
                _request(source_id, renderer=renderer),
                uow=uow,
                storage=runtime.storage,
                moment=utc_now(),
            )
            uow.commit()

    assert _counts(url) == (2, 2)

    # And the same renderer with the same parameters is refused, which is the other side
    # of the same constraint: one derivation, one result.
    refusal = pytest.raises(Exception, match=r"uq_file_derivations|duplicate key")
    with refusal, runtime.uow_factory() as uow:
        record_derivation(
            _request(source_id, renderer="preview-1.0"),
            uow=uow,
            storage=runtime.storage,
            moment=utc_now(),
        )
        uow.commit()


def test_a_derivative_inherits_its_sources_visibility(world: dict[str, Any]) -> None:
    """A preview of an internal file is internal.

    Letting the renderer choose would put an access decision in the least considered
    place in the system — and a preview is the artifact most likely to be shown to
    somebody, so getting it wrong is the version that leaks.
    """

    from app.core.time import utc_now
    from app.files.derivation import record_derivation

    client, runtime, url = world["client"], world["runtime"], world["url"]
    token = sign_in(client)
    source_id = upload(client, token, purpose="misc_internal", filename="internal.png")

    with runtime.uow_factory() as uow:
        result = record_derivation(
            _request(source_id), uow=uow, storage=runtime.storage, moment=utc_now()
        )
        uow.commit()

    with psycopg.connect(_psycopg(url)) as connection:
        row = connection.execute(
            "SELECT category, visibility_scope FROM file_objects WHERE id = %s",
            (result.derived_file_id,),
        ).fetchone()
    assert row == ("misc_internal", "internal_only")


def test_finalising_a_previewable_file_enqueues_one_event(world: dict[str, Any]) -> None:
    """JOB-PREVIEW-001. `15_Agent_Implementation_Plan.md:698`.

    In the same transaction as the state change it describes, which is what makes "the
    file became available" and "somebody was told" either both durable or both absent.
    """

    client, url = world["client"], world["url"]
    file_id = upload(client, sign_in(client))

    with psycopg.connect(_psycopg(url)) as connection:
        rows = connection.execute(
            "SELECT event_type, aggregate_id, payload::text FROM outbox_events "
            "WHERE event_type = 'FilePreviewRequested'"
        ).fetchall()

    assert len(rows) == 1
    assert str(rows[0][1]) == file_id
    assert file_id in rows[0][2]


def test_a_file_that_cannot_be_previewed_enqueues_nothing(world: dict[str, Any]) -> None:
    """A CSV has no page to show. Dispatching for one would enqueue work no renderer
    could do, and a queue is the wrong place to discover that."""

    client, url = world["client"], world["url"]
    upload(
        client,
        sign_in(client),
        content=CSV,
        media_type="text/csv",
        purpose="bank_statement",
        filename="statement.csv",
    )

    with psycopg.connect(_psycopg(url)) as connection:
        count = connection.execute(
            "SELECT count(*) FROM outbox_events WHERE event_type = 'FilePreviewRequested'"
        ).fetchone()
    assert count and count[0] == 0


def test_a_quarantined_file_enqueues_no_preview(world: dict[str, Any]) -> None:
    """JOB-PREVIEW-001's fail-closed half.

    Rendering a preview of quarantined content would put the renderer in front of the
    bytes inspection has just refused — which is the one place a malicious file would most
    like to be.
    """

    client, url = world["client"], world["url"]
    upload(
        client,
        sign_in(client),
        content=b"\x7fELF\x02\x01\x01" + b"\x00" * 64,
        media_type="image/png",
        purpose="misc_internal",
        filename="photo.png",
    )

    with psycopg.connect(_psycopg(url)) as connection:
        count = connection.execute(
            "SELECT count(*) FROM outbox_events WHERE event_type = 'FilePreviewRequested'"
        ).fetchone()
    assert count and count[0] == 0


def test_the_preview_route_reports_processing_rather_than_failing(
    world: dict[str, Any],
) -> None:
    """JOB-PREVIEW-002.

    **Rewritten in M8 slice 5, and the old assertion is why this test mattered.** M4 had nothing to
    render with, so the route served the original bytes and this test pinned exactly that:
    `response.content == PNG`. It was a truthful answer then and it was also the thing slice 5 had
    to remove — while the route served the source, a `file.preview` grant acted as a `file.download`
    grant, which is the separation `05_API_Specification.md:1045` asks for.

    The requirement is unchanged; its answer is not. A preview request still produces a stated
    outcome rather than a 500 or an empty body, and that outcome is now a *derived* page image.
    Asserted as an inequality against the uploaded bytes, because that is the form with teeth: an
    equality would pass again the moment somebody reintroduced the passthrough.

    Even for a PNG source the preview differs — the page is rasterised and re-encoded, so the bytes
    are the renderer's rather than the uploader's. The `file_derivations` row accounting for it is
    asserted in `tests/integration/test_segment_intake.py`.
    """

    client = world["client"]
    token = sign_in(client)
    file_id = upload(client, token)

    response = client.get(f"/api/v1/files/{file_id}/preview")
    assert response.status_code == 200, response.text
    assert response.content != PNG, "the preview served the uploaded file rather than a derivative"
    assert response.content.startswith(b"\x89PNG"), "a preview is a page image"
    assert response.headers["Cache-Control"] == "no-store"
    # The dimensions a client needs before it can send `client_source_dimensions`.
    assert response.headers["X-Preview-Pixel-Width"]
    assert response.headers["X-Preview-Renderer-Version"].startswith("pypdfium2/")
