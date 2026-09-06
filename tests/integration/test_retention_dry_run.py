"""What retention would remove, and the two ways that report could lie. M11 slice 6B.

`15_Agent_Implementation_Plan.md:1318`.

§19.5 asks for "retention dry run and approved execution only". This is the dry run, and the two
properties worth testing are not "does it count correctly" — they are the ways a correct-looking
count would mislead:

- **an unresolvable policy must not read as zero.** `resource_type` has no approved vocabulary, so
  a policy can name something nothing here can query. Reporting `eligible=0` for it would say
  "nothing would be deleted" when the truth is "nobody knows".
- **a legal hold must win.** A row under an unreleased hold is excluded from what would expire and
  counted separately, so the report can never suggest deleting something a hold covers.

Plus the one that makes it a dry run at all: **it deletes nothing**, asserted by counting rows
before and after.

**No `Covers:` line, deliberately.** The milestone's maintenance-job obligation is about each of
§19.5's five and this is the second. Naming that obligation here would be citing it, which the
traceability gate treats as a claim of coverage — and it caught exactly that in slice 6A's first
draft. Its entry in `tests/backend/test_traceability.py` carries the survey of why three of the
five must not be built at all.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

ADMIN = "retention_admin"


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
    from app.security.passwords import Argon2Parameters, hash_password

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=tmp_path_factory.mktemp("retention-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="y" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password("correct-horse-battery-staple", parameters, max_length=128)

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES (%s, 'Retention Admin', %s, 'active')",
            (ADMIN, encoded),
        )
        connection.commit()

    runtime = RuntimeServices.from_settings(settings)
    yield {"runtime": runtime, "owner_url": migrated.owner_url}
    runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(autouse=True)
def a_clean_slate(world: dict[str, Any]) -> Iterator[None]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute("DELETE FROM legal_holds")
        connection.execute("DELETE FROM retention_policies")
        connection.execute("DELETE FROM file_objects")
        connection.commit()
    yield


def activate_policy(
    world: dict[str, Any], *, resource_type: str, retention_seconds: int
) -> uuid.UUID:
    """One policy that has been through proposal, approval and activation.

    All three actor columns are set because the schema demands it: `activated_at IS NULL OR
    approved_at IS NOT NULL` is a CHECK, and it is the separation of proposer from approver that
    the three columns exist to express.
    """

    policy_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO retention_policies (id, resource_type, retention_class, "
            "retention_seconds, version, status, proposed_by_admin_user_id, proposed_at, "
            "approved_by_admin_user_id, approved_at, activated_by_admin_user_id, activated_at) "
            "SELECT %s, %s, 'standard', %s, 1, 'active', u.id, now(), u.id, now(), u.id, now() "
            "FROM admin_users u WHERE u.username = %s",
            (policy_id, resource_type, retention_seconds, ADMIN),
        )
        connection.commit()
    return policy_id


def seed_file(world: dict[str, Any], *, age: timedelta) -> uuid.UUID:
    file_id = uuid.uuid4()
    created = datetime.now(UTC) - age
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata, created_at) "
            "VALUES (%s, 'local', 'gold', %s, 'f.bin', 'application/pdf', 10, %s, "
            "'payment_evidence', 'internal', 'available', 'clean', 'trader_user', "
            "'original', '{}', %s)",
            (file_id, f"retention/{file_id}", uuid.uuid4().hex * 2, created),
        )
        connection.commit()
    return file_id


def place_hold(world: dict[str, Any], *, resource_id: uuid.UUID, released: bool = False) -> None:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO legal_holds (id, resource_type, resource_id, reason, "
            "placed_by_admin_user_id, placed_at, released_by_admin_user_id, released_at, "
            "release_reason) "
            "SELECT %s, 'file_object', %s, 'a dispute', u.id, now(), "
            "CASE WHEN %s THEN u.id ELSE NULL END, "
            "CASE WHEN %s THEN now() ELSE NULL END, "
            "CASE WHEN %s THEN 'settled' ELSE NULL END "
            "FROM admin_users u WHERE u.username = %s",
            (uuid.uuid4(), resource_id, released, released, released, ADMIN),
        )
        connection.commit()


def run(world: dict[str, Any]) -> Any:
    from app.retention.dry_run import plan_retention

    with world["runtime"].uow_factory() as uow:
        report = plan_retention(uow.session, now=datetime.now(UTC))
        uow.rollback()
    return report


def test_nothing_activated_reports_nothing(world: dict[str, Any]) -> None:
    """Today's real answer, and it must be an empty report rather than an error."""

    seed_file(world, age=timedelta(days=3650))
    report = run(world)

    assert report.impacts == ()
    assert report.total_eligible == 0
    assert report.unresolved == ()


def test_a_policy_that_was_never_activated_is_ignored(world: dict[str, Any]) -> None:
    """Proposed and approved is not activated. The workflow's whole point is that they differ."""

    seed_file(world, age=timedelta(days=3650))
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO retention_policies (id, resource_type, retention_class, "
            "retention_seconds, version, status, proposed_by_admin_user_id, proposed_at, "
            "approved_by_admin_user_id, approved_at) "
            "SELECT %s, 'file_object', 'standard', 60, 1, 'approved', u.id, now(), u.id, now() "
            "FROM admin_users u WHERE u.username = %s",
            (uuid.uuid4(), ADMIN),
        )
        connection.commit()

    assert run(world).impacts == ()


def test_an_activated_policy_counts_only_what_is_older_than_it(world: dict[str, Any]) -> None:
    """The ordinary case, with a row on each side of the cutoff.

    Both rows are needed: a test with only the old one passes against a job that counts every file
    regardless of age.
    """

    activate_policy(world, resource_type="file_object", retention_seconds=86_400)
    seed_file(world, age=timedelta(days=30))
    seed_file(world, age=timedelta(hours=1))

    report = run(world)
    assert len(report.impacts) == 1
    assert report.impacts[0].eligible == 1
    assert report.total_eligible == 1


def test_a_legal_hold_protects_a_row_that_would_otherwise_expire(world: dict[str, Any]) -> None:
    """Step four of the approved workflow, applied here rather than left to a job that does not
    exist.

    Both files are old enough to expire; one is held. The held one must be counted as protected and
    excluded from `eligible`, so the report can never suggest removing it.
    """

    activate_policy(world, resource_type="file_object", retention_seconds=86_400)
    seed_file(world, age=timedelta(days=30))
    held = seed_file(world, age=timedelta(days=30))
    place_hold(world, resource_id=held)

    impact = run(world).impacts[0]
    assert impact.eligible == 1
    assert impact.protected_by_legal_hold == 1


def test_a_released_hold_stops_protecting(world: dict[str, Any]) -> None:
    """A released hold is history. Treating it as live would make retention impossible to apply.

    The opposite error to the one above, and just as wrong — which is why both directions are
    asserted rather than only the protective one.
    """

    activate_policy(world, resource_type="file_object", retention_seconds=86_400)
    once_held = seed_file(world, age=timedelta(days=30))
    place_hold(world, resource_id=once_held, released=True)

    impact = run(world).impacts[0]
    assert impact.eligible == 1
    assert impact.protected_by_legal_hold == 0


def test_an_unresolvable_resource_type_is_unknown_and_never_zero(world: dict[str, Any]) -> None:
    """**The property this module exists to protect.**

    A policy naming something nothing can query must report `resolvable=False` with `eligible=None`
    — not `eligible=0`. One says "nobody knows what would be deleted"; the other says "nothing
    would be deleted", and a retention report that confuses them is worse than no report.
    """

    activate_policy(world, resource_type="receipt_segment", retention_seconds=60)
    report = run(world)

    impact = report.impacts[0]
    assert impact.resolvable is False
    assert impact.eligible is None, "an unknown impact was reported as a count"
    assert impact.protected_by_legal_hold is None
    assert report.unresolved == ("receipt_segment",)
    # And the total must not quietly absorb it as a zero.
    assert report.total_eligible == 0
    assert report.unresolved, "the totals look calm; only `unresolved` says why"


def test_the_dry_run_deletes_nothing(world: dict[str, Any]) -> None:
    """What makes it a dry run. Counted before and after, because a report is not evidence."""

    activate_policy(world, resource_type="file_object", retention_seconds=1)
    for _ in range(3):
        seed_file(world, age=timedelta(days=30))

    before = _file_count(world)
    report = run(world)
    after = _file_count(world)

    assert report.total_eligible == 3, "the fixture did not make anything eligible"
    assert before == after == 3, "the dry run removed rows"


def _file_count(world: dict[str, Any]) -> int:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute("SELECT count(*) FROM file_objects").fetchone()
    assert row is not None
    return int(row[0])
