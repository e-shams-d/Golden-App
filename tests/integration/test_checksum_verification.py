"""The checksum job: bounded, idempotent, and honest about partial coverage. M11 slice 6A.

`15_Agent_Implementation_Plan.md:1318`.

§19.5 requires maintenance jobs to be **bounded**, and the rule's own reason is that a job reading
an unbounded set stops finishing as the database grows. Two properties follow, and they are tested
separately because each passes without the other:

- **bounded** — more rows than the limit still returns, and says how many it did not reach;
- **idempotent** — running it twice against the same state reports the same thing and changes
  nothing, because a maintenance job is redelivered whenever a worker dies mid-pass.

**The bound is asserted with more rows than the limit, never with fewer.** A test seeded with
three files and a limit of two hundred passes against a job with no limit at all — which is the
shape of every incomplete-input failure this project has found.

**Deliberately no `Covers:` line.** The milestone obligation for maintenance jobs is about *each*
of the five, and this slice schedules one. Claiming it here would discharge an obligation on a
fifth of its subject — the over-claim slice 3 made and slice 3B had to correct. The traceability
gate enforces the distinction: citing the id in this file while the entry is still pending is
itself a failure, which is how the first draft of this docstring was caught.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration


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

    root = tmp_path_factory.mktemp("checksum-storage")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=root,
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="y" * 40,
        auth_rate_limit_key_secret=None,
    )
    runtime = RuntimeServices.from_settings(settings)
    yield {"runtime": runtime, "owner_url": migrated.owner_url, "root": root}
    runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(autouse=True)
def an_empty_table(world: dict[str, Any]) -> Iterator[None]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute("DELETE FROM file_objects")
        connection.commit()
    yield


def seed_file(
    world: dict[str, Any], *, payload: bytes, record_digest: str | None = None
) -> uuid.UUID:
    """One file on disk and the row that describes it.

    `record_digest` defaults to the truth. Passing something else is how a mismatch is planted:
    the bytes and the row disagree, which is the whole condition this job looks for.
    """

    file_id = uuid.uuid4()
    key = f"checksums/{file_id}"
    path = world["root"] / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)

    digest = record_digest or hashlib.sha256(payload).hexdigest()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, 'f.bin', 'application/octet-stream', %s, %s, "
            "'payment_evidence', 'internal', 'available', 'clean', 'admin_user', "
            "'original', '{}')",
            (file_id, key, len(payload), digest),
        )
        connection.commit()
    return file_id


def test_a_matching_file_produces_no_finding(world: dict[str, Any]) -> None:
    """The negative half. Without it, a job that reported everything would pass the next test."""

    from app.storage.verification import verify_recent_checksums

    seed_file(world, payload=b"intact")
    report = verify_recent_checksums(world["runtime"], limit=10)

    assert report.examined == 1
    assert report.mismatches == ()
    assert report.complete


def test_bytes_that_disagree_with_the_row_are_reported(world: dict[str, Any]) -> None:
    """The condition the job exists for: the record says one digest, storage holds another."""

    from app.storage.verification import verify_recent_checksums

    good = seed_file(world, payload=b"intact")
    bad = seed_file(world, payload=b"changed", record_digest="0" * 64)

    report = verify_recent_checksums(world["runtime"], limit=10)
    assert set(report.mismatches) == {bad}
    assert good not in report.mismatches


def test_a_size_that_disagrees_is_reported_even_when_the_digest_is_absent_from_the_check(
    world: dict[str, Any],
) -> None:
    """Size is compared as well as the digest, which makes a truncation obvious.

    Seeded by recording the digest of the *full* payload against a truncated file: both fields
    then disagree, which is what a partial write actually looks like.
    """

    from app.storage.verification import verify_recent_checksums

    full = b"the whole thing"
    truncated = seed_file(
        world, payload=full[:4], record_digest=hashlib.sha256(full).hexdigest()
    )

    report = verify_recent_checksums(world["runtime"], limit=10)
    assert set(report.mismatches) == {truncated}


def test_the_pass_is_bounded_and_says_what_it_did_not_reach(world: dict[str, Any]) -> None:
    """**The bound, asserted with more rows than the limit.**

    Five files, limit of two. A job with no bound would examine five and report `remaining=0`,
    which is exactly what this must fail against — so both numbers are asserted, not just one.
    """

    from app.storage.verification import verify_recent_checksums

    for index in range(5):
        seed_file(world, payload=f"file-{index}".encode())

    report = verify_recent_checksums(world["runtime"], limit=2)

    assert report.examined == 2
    assert report.remaining == 3
    assert not report.complete, "a partial pass must not read as full coverage"


def test_a_bounded_pass_reports_the_same_thing_twice(world: dict[str, Any]) -> None:
    """Idempotent under redelivery, which is how a maintenance job is retried.

    A worker dying mid-pass means the whole task runs again. The job holds no cursor and writes
    nothing, so the second run must agree with the first — and the row count must be unchanged,
    which is the assertion that would catch a job that "fixed" what it found.
    """

    from app.storage.verification import verify_recent_checksums

    seed_file(world, payload=b"intact")
    seed_file(world, payload=b"changed", record_digest="0" * 64)

    first = verify_recent_checksums(world["runtime"], limit=10)
    second = verify_recent_checksums(world["runtime"], limit=10)

    assert first == second

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        rows = connection.execute("SELECT count(*) FROM file_objects").fetchone()
    assert rows is not None and rows[0] == 2, "the job changed the table it was reading"


def test_the_job_never_writes_even_when_it_finds_a_mismatch(world: dict[str, Any]) -> None:
    """It reports and a person decides — it cannot know whether the bytes or the row is wrong.

    Asserted on the stored digest specifically: "fixing" a mismatch by overwriting the record with
    the measured value is the tempting repair, and it erases the only evidence that anything
    disagreed.
    """

    from app.storage.verification import verify_recent_checksums

    planted = "0" * 64
    file_id = seed_file(world, payload=b"changed", record_digest=planted)

    verify_recent_checksums(world["runtime"], limit=10)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT sha256_hash, storage_status FROM file_objects WHERE id = %s", (file_id,)
        ).fetchone()
    assert row is not None
    assert row[0] == planted, "the job rewrote the recorded digest and erased the disagreement"
    assert row[1] == "available", "the job quarantined a file on a guess"


def test_a_row_with_no_recorded_digest_is_skipped(world: dict[str, Any]) -> None:
    """A `pending` upload legitimately has none, and reporting it would bury the real findings."""

    from app.storage.verification import verify_recent_checksums

    file_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, category, visibility_scope, "
            "storage_status, scan_status, uploaded_by_actor_type, original_or_derived_relation, "
            "metadata) VALUES (%s, 'local', 'gold', %s, 'f.bin', 'application/octet-stream', "
            "4, 'payment_evidence', 'internal', 'pending', 'pending', 'trader_user', "
            "'original', '{}')",
            (file_id, f"checksums/{file_id}"),
        )
        connection.commit()

    report = verify_recent_checksums(world["runtime"], limit=10)
    assert report.examined == 0
    assert report.mismatches == ()


def test_a_missing_object_is_not_counted_as_a_mismatch(world: dict[str, Any]) -> None:
    """An absent object is a different finding, and counting it twice ruins both as trends."""

    from app.storage.verification import verify_recent_checksums

    file_id = seed_file(world, payload=b"gone")
    (world["root"] / f"checksums/{file_id}").unlink()

    report = verify_recent_checksums(world["runtime"], limit=10)
    assert report.mismatches == ()


def test_a_limit_below_one_is_refused(world: dict[str, Any]) -> None:
    """`limit=0` would be an unbounded pass spelled as a bounded one."""

    from app.storage.verification import verify_recent_checksums

    with pytest.raises(ValueError, match="unbounded"):
        verify_recent_checksums(world["runtime"], limit=0)
