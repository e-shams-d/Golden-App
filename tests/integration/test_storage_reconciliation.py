"""The seven reconciliation conditions, each simulated and each detected.

FILE-RECON-001..007. Every test here creates a real disagreement between a real
PostgreSQL and a real filesystem, then asserts the detector finds it — and, just as
importantly, that the other detectors do not.

The last class is the one that matters most: **no detection run deletes anything.**
Row counts and storage keys are captured before and after, and the app role's
withheld DELETE privilege is used as a second, independent check. A reconciliation
routine that repairs by deleting is a routine that destroys financial evidence the
first time it is wrong about a row being orphaned.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic_runner import run_alembic
from app.storage.local import LocalStorageBackend
from app.storage.reconciliation import (
    CONDITIONS,
    checksum_mismatches,
    derivatives_without_a_derivation,
    detect_all,
    duplicate_object_writes,
    records_without_a_storage_object,
    stale_pending_uploads,
    storage_objects_without_a_record,
    stuck_processing_jobs,
)
from bootstrap_replay import RuntimeIdentities
from file_fixtures import FIXTURES_BY_NAME
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
RECEIPT = FIXTURES_BY_NAME["valid_pdf_receipt"]
DUPLICATE = FIXTURES_BY_NAME["duplicate_pdf_receipt"]
OTHER = FIXTURES_BY_NAME["valid_png_photo"]


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageBackend:
    backend = LocalStorageBackend(tmp_path / "objects")
    backend.check_available()
    return backend


def _sqlalchemy_url(url: str) -> str:
    """Force the psycopg 3 driver.

    The fixture hands back whatever scheme `INTEGRATION_ADMIN_DATABASE_URL` carries,
    and a bare `postgresql://` makes SQLAlchemy reach for psycopg2, which is not
    installed. Naming the driver keeps the test working whichever form the
    environment variable takes.
    """

    if url.startswith("postgresql+"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def connection(migrated_database: str) -> Iterator[Connection]:
    """A SQLAlchemy connection, because the detectors take one.

    Autocommit, so a detector's read sees what the test just inserted without the
    test having to manage a transaction around each step.
    """

    engine = create_engine(_sqlalchemy_url(migrated_database), future=True)
    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        try:
            yield conn
        finally:
            conn.rollback()
            for table in ("file_derivations", "file_links", "file_objects", "processing_jobs"):
                conn.execute(text(f"DELETE FROM {table}"))
            conn.commit()
    engine.dispose()


def record_file(
    connection: Connection,
    *,
    key: str,
    sha256: str | None,
    size: int,
    status: str = "available",
    scan: str = "clean",
    relation: str = "original",
    created_at: datetime = NOW,
) -> uuid.UUID:
    row = connection.execute(
        text(
            "INSERT INTO file_objects (storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, created_at) "
            "VALUES ('local', 'uploads', :key, :filename, 'application/pdf', :size, "
            ":sha256, 'bank_receipt', 'internal', :status, :scan, 'trader_user', "
            ":relation, :created_at) RETURNING id"
        ),
        {
            "key": key,
            "filename": RECEIPT.upload_filename,
            "size": size,
            "sha256": sha256,
            "status": status,
            "scan": scan,
            "relation": relation,
            "created_at": created_at,
        },
    ).scalar_one()
    connection.commit()
    return row


def store(storage: LocalStorageBackend, key: str, content: bytes) -> None:
    storage.write(key, io.BytesIO(content))


class TestTheConditionListIsComplete:
    def test_there_are_exactly_seven(self) -> None:
        """The plan names seven required conditions. A detector added without a
        condition identifier would produce findings nothing can group."""

        assert len(CONDITIONS) == 7
        assert len(set(CONDITIONS)) == 7


class TestStorageObjectWithoutARecord:
    """FILE-RECON-001. Bytes nobody is accounting for, growing forever."""

    def test_an_orphaned_object_is_detected(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        store(storage, "bank_receipt/2026/08/06/orphan", RECEIPT.content)

        findings = storage_objects_without_a_record(connection, storage)

        assert [f.storage_key for f in findings] == ["bank_receipt/2026/08/06/orphan"]

    def test_a_recorded_object_is_not_reported(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        """Guard the guard: a detector that flags everything is a detector nobody
        can act on."""

        key = "bank_receipt/2026/08/06/recorded"
        store(storage, key, RECEIPT.content)
        record_file(connection, key=key, sha256=RECEIPT.sha256, size=RECEIPT.size_bytes)

        assert storage_objects_without_a_record(connection, storage) == []

    def test_a_leftover_partial_write_is_not_an_orphan(
        self, connection: Connection, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        """A worker killed mid-write leaves a `.partial-` file and runs no cleanup.

        `check_available` and `write` both tidy up after themselves, so asserting
        against them proves nothing — a negative control showed exactly that. SIGKILL
        is what leaves the file, and it is created directly here because that is the
        state a killed process leaves.

        Reporting it as an orphaned object would put a finding in the report on every
        killed worker, and an operator who learns to ignore this report will ignore
        the real finding beside it.
        """

        storage.check_available()
        (tmp_path / "objects" / "bank_receipt").mkdir(parents=True, exist_ok=True)
        (tmp_path / "objects" / "bank_receipt" / ".partial-deadbeef").write_bytes(b"half")

        assert storage_objects_without_a_record(connection, storage) == []


class TestRecordWithoutAStorageObject:
    """FILE-RECON-002. A row promising evidence that is not there."""

    def test_a_missing_object_is_detected(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        file_id = record_file(
            connection,
            key="bank_receipt/2026/08/06/vanished",
            sha256=RECEIPT.sha256,
            size=RECEIPT.size_bytes,
        )

        findings = records_without_a_storage_object(connection, storage)

        assert [f.file_id for f in findings] == [file_id]

    def test_a_present_object_is_not_reported(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        key = "bank_receipt/2026/08/06/present"
        store(storage, key, RECEIPT.content)
        record_file(connection, key=key, sha256=RECEIPT.sha256, size=RECEIPT.size_bytes)

        assert records_without_a_storage_object(connection, storage) == []


class TestStalePendingUpload:
    """FILE-RECON-003. A row that never left `pending`."""

    def test_an_old_pending_row_is_detected(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        file_id = record_file(
            connection,
            key="bank_receipt/2026/08/05/stuck",
            sha256=None,
            size=0,
            status="pending",
            scan="pending",
            created_at=NOW - timedelta(days=1),
        )

        findings = stale_pending_uploads(connection, now=NOW, older_than=timedelta(hours=6))

        assert [f.file_id for f in findings] == [file_id]

    def test_a_recent_pending_row_is_not_reported(self, connection: Connection) -> None:
        """An upload in progress is not a fault. A cutoff that caught it would bury
        the real findings under ordinary traffic."""

        record_file(
            connection,
            key="bank_receipt/2026/08/06/in-progress",
            sha256=None,
            size=0,
            status="pending",
            scan="pending",
            created_at=NOW - timedelta(minutes=5),
        )

        assert stale_pending_uploads(connection, now=NOW, older_than=timedelta(hours=6)) == []

    def test_the_cutoff_is_an_argument_and_changes_the_answer(self, connection: Connection) -> None:
        """A detector that decided its own threshold would give a different answer
        when a config file changed, and an operator confirming a finding needs the
        same answer twice."""

        record_file(
            connection,
            key="bank_receipt/2026/08/06/an-hour-old",
            sha256=None,
            size=0,
            status="pending",
            scan="pending",
            created_at=NOW - timedelta(hours=1),
        )

        strict = stale_pending_uploads(connection, now=NOW, older_than=timedelta(minutes=30))
        lenient = stale_pending_uploads(connection, now=NOW, older_than=timedelta(hours=6))

        assert len(strict) == 1
        assert lenient == []


class TestDerivativeWithoutADerivation:
    """FILE-RECON-004. Provenance that cannot be reconstructed."""

    def test_a_derivative_with_no_derivation_row_is_detected(self, connection: Connection) -> None:
        file_id = record_file(
            connection,
            key="crop/2026/08/06/orphan-crop",
            sha256=OTHER.sha256,
            size=OTHER.size_bytes,
            relation="derived",
        )

        findings = derivatives_without_a_derivation(connection)

        assert [f.file_id for f in findings] == [file_id]

    def test_a_derivative_with_its_derivation_is_not_reported(self, connection: Connection) -> None:
        source = record_file(
            connection,
            key="bank_receipt/2026/08/06/source",
            sha256=RECEIPT.sha256,
            size=RECEIPT.size_bytes,
        )
        derived = record_file(
            connection,
            key="crop/2026/08/06/derived",
            sha256=OTHER.sha256,
            size=OTHER.size_bytes,
            relation="derived",
        )
        connection.execute(
            text(
                "INSERT INTO file_derivations (source_file_id, derived_file_id, "
                "derivation_type, parameters_hash, renderer_version, source_hash) "
                "VALUES (:source, :derived, 'crop', :params, 'cropper-1.0.0', :source_hash)"
            ),
            {
                "source": source,
                "derived": derived,
                "params": f"v1:{'c' * 64}",
                "source_hash": RECEIPT.sha256,
            },
        )
        connection.commit()

        assert derivatives_without_a_derivation(connection) == []

    def test_an_original_is_never_reported(self, connection: Connection) -> None:
        record_file(
            connection,
            key="bank_receipt/2026/08/06/an-original",
            sha256=RECEIPT.sha256,
            size=RECEIPT.size_bytes,
            relation="original",
        )

        assert derivatives_without_a_derivation(connection) == []


class TestChecksumMismatch:
    """FILE-RECON-005. The one condition that means something impossible happened."""

    def test_altered_bytes_are_detected(
        self, connection: Connection, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        """The bytes are changed on disk behind the backend's back, which is what a
        corruption or a tamper looks like."""

        key = "bank_receipt/2026/08/06/altered"
        store(storage, key, RECEIPT.content)
        record_file(connection, key=key, sha256=RECEIPT.sha256, size=RECEIPT.size_bytes)

        (tmp_path / "objects" / key).write_bytes(OTHER.content)

        findings = checksum_mismatches(connection, storage)

        assert len(findings) == 1
        assert RECEIPT.sha256 in findings[0].detail
        assert OTHER.sha256 in findings[0].detail

    def test_matching_content_is_not_reported(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        key = "bank_receipt/2026/08/06/intact"
        store(storage, key, RECEIPT.content)
        record_file(connection, key=key, sha256=RECEIPT.sha256, size=RECEIPT.size_bytes)

        assert checksum_mismatches(connection, storage) == []

    def test_a_row_with_no_recorded_digest_is_skipped(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        """A `pending` upload legitimately has no digest yet. Reporting it here
        would bury the real finding under the ordinary ones."""

        key = "bank_receipt/2026/08/06/not-yet-hashed"
        store(storage, key, RECEIPT.content)
        record_file(connection, key=key, sha256=None, size=0, status="pending", scan="pending")

        assert checksum_mismatches(connection, storage) == []

    def test_a_missing_object_is_not_double_counted_here(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        """It is FILE-RECON-002's finding. Reporting it twice would make an operator
        chase two problems that are one."""

        record_file(
            connection,
            key="bank_receipt/2026/08/06/gone",
            sha256=RECEIPT.sha256,
            size=RECEIPT.size_bytes,
        )

        assert checksum_mismatches(connection, storage) == []
        assert len(records_without_a_storage_object(connection, storage)) == 1

    def test_a_truncation_that_kept_the_digest_column_is_still_caught_by_size(
        self, connection: Connection, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        """Size is compared as well as digest, which makes a truncation obvious in
        the report rather than only detectable."""

        key = "bank_receipt/2026/08/06/truncated"
        store(storage, key, RECEIPT.content)
        record_file(connection, key=key, sha256=RECEIPT.sha256, size=RECEIPT.size_bytes)

        (tmp_path / "objects" / key).write_bytes(RECEIPT.content[:10])

        findings = checksum_mismatches(connection, storage)

        assert len(findings) == 1
        assert "10 bytes" in findings[0].detail


class TestStuckProcessingJob:
    """FILE-RECON-006. Claimed, stopped heartbeating, never finished."""

    def insert_job(
        self,
        connection: Connection,
        *,
        status: str,
        started_at: datetime | None,
        heartbeat_at: datetime | None,
        locked_by: str | None = "worker-7",
    ) -> uuid.UUID:
        job_id = connection.execute(
            text(
                "INSERT INTO processing_jobs (job_type, queue_name, status, started_at, "
                "heartbeat_at, locked_by, attempt_count) "
                "VALUES ('file.scan', 'files', :status, :started_at, :heartbeat_at, "
                ":locked_by, 1) RETURNING id"
            ),
            {
                "status": status,
                "started_at": started_at,
                "heartbeat_at": heartbeat_at,
                "locked_by": locked_by,
            },
        ).scalar_one()
        connection.commit()
        return job_id

    def test_a_silent_job_is_detected(self, connection: Connection) -> None:
        job_id = self.insert_job(
            connection,
            status="running",
            started_at=NOW - timedelta(hours=2),
            heartbeat_at=NOW - timedelta(hours=1),
        )

        findings = stuck_processing_jobs(connection, now=NOW, silent_for=timedelta(minutes=30))

        assert [f.job_id for f in findings] == [job_id]

    def test_the_schema_forbids_a_claim_with_no_heartbeat(self, connection: Connection) -> None:
        """Which is why the detector's `COALESCE` is not about that case.

        `ck_processing_jobs_lease_fields_move_together` makes "claimed but never
        heartbeat" unrepresentable, so a fallback written for it would be defending
        against a state the database already prevents. Asserted here so the next
        reader of that `COALESCE` knows what it is really for.
        """

        with pytest.raises(IntegrityError, match="lease_fields_move_together"):
            self.insert_job(
                connection,
                status="running",
                started_at=NOW - timedelta(hours=2),
                heartbeat_at=None,
                locked_by="worker-7",
            )
        connection.rollback()

    def test_a_processing_row_holding_no_lease_at_all_is_detected(
        self, connection: Connection
    ) -> None:
        """The case the fallback exists for, and it is reachable.

        Nothing ties `status = 'processing'` to holding a lease, so a row can be
        processing with both lease columns null — set by hand, or by a path that
        advanced the status without claiming. `started_at` is then the only signal
        of age, and a predicate reading `heartbeat_at` alone would never see it.
        """

        job_id = self.insert_job(
            connection,
            status="running",
            started_at=NOW - timedelta(hours=2),
            heartbeat_at=None,
            locked_by=None,
        )

        findings = stuck_processing_jobs(connection, now=NOW, silent_for=timedelta(minutes=30))

        assert [f.job_id for f in findings] == [job_id]

    def test_a_live_job_is_not_reported(self, connection: Connection) -> None:
        self.insert_job(
            connection,
            status="running",
            started_at=NOW - timedelta(minutes=10),
            heartbeat_at=NOW - timedelta(seconds=20),
        )

        assert stuck_processing_jobs(connection, now=NOW, silent_for=timedelta(minutes=30)) == []


class TestDuplicateObjectWrite:
    """FILE-RECON-007. A retry that wrote before recording."""

    def test_two_rows_with_identical_content_are_detected(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        for key in ("bank_receipt/2026/08/06/first", "bank_receipt/2026/08/06/second"):
            store(storage, key, RECEIPT.content)
            record_file(connection, key=key, sha256=RECEIPT.sha256, size=RECEIPT.size_bytes)

        findings = duplicate_object_writes(connection)

        assert len(findings) == 1
        assert "2 rows share digest" in findings[0].detail
        assert "first" in findings[0].detail and "second" in findings[0].detail

    def test_the_duplicate_fixture_is_representable_and_detected(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        """FILE-META-005 end to end: the same document uploaded twice is data to
        detect and report, not data to reject."""

        assert RECEIPT.sha256 == DUPLICATE.sha256

        for name, fixture in (("original", RECEIPT), ("copy", DUPLICATE)):
            key = f"bank_receipt/2026/08/06/{name}"
            store(storage, key, fixture.content)
            record_file(connection, key=key, sha256=fixture.sha256, size=fixture.size_bytes)

        assert len(duplicate_object_writes(connection)) == 1

    def test_distinct_content_is_not_reported(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        for key, fixture in (
            ("bank_receipt/2026/08/06/a", RECEIPT),
            ("bank_receipt/2026/08/06/b", OTHER),
        ):
            store(storage, key, fixture.content)
            record_file(connection, key=key, sha256=fixture.sha256, size=fixture.size_bytes)

        assert duplicate_object_writes(connection) == []


class TestDetectionNeverDeletesAnything:
    """The guarantee, asserted three independent ways.

    An automated repair for "an object with no record" is a routine that deletes
    files whose row is temporarily missing, and the first time it is wrong it
    destroys evidence no backup restores selectively.
    """

    def seed_every_condition(
        self, connection: Connection, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        # 1: an orphaned object
        store(storage, "bank_receipt/2026/08/06/orphan", OTHER.content)
        # 2: a record with no object
        record_file(
            connection, key="bank_receipt/2026/08/06/vanished", sha256=RECEIPT.sha256, size=1
        )
        # 3: a stale pending upload
        record_file(
            connection,
            key="bank_receipt/2026/08/05/stale",
            sha256=None,
            size=0,
            status="pending",
            scan="pending",
            created_at=NOW - timedelta(days=2),
        )
        # 4: a derivative with no derivation
        record_file(
            connection,
            key="crop/2026/08/06/orphan-crop",
            sha256=OTHER.sha256,
            size=OTHER.size_bytes,
            relation="derived",
        )
        # 5: a checksum mismatch
        mismatched = "bank_receipt/2026/08/06/altered"
        store(storage, mismatched, RECEIPT.content)
        record_file(connection, key=mismatched, sha256=RECEIPT.sha256, size=RECEIPT.size_bytes)
        (tmp_path / "objects" / mismatched).write_bytes(OTHER.content)
        # 6: a stuck job
        connection.execute(
            text(
                "INSERT INTO processing_jobs (job_type, queue_name, status, started_at, "
                "heartbeat_at, locked_by, attempt_count) VALUES ('file.scan', 'files', "
                "'running', :started, :heartbeat, 'worker-9', 1)"
            ),
            # Both lease columns, because the schema requires them to move together.
            {"started": NOW - timedelta(hours=3), "heartbeat": NOW - timedelta(hours=3)},
        )
        # 7: a duplicate write
        for suffix in ("dup-a", "dup-b"):
            key = f"bank_receipt/2026/08/06/{suffix}"
            store(storage, key, DUPLICATE.content)
            record_file(connection, key=key, sha256=DUPLICATE.sha256, size=DUPLICATE.size_bytes)
        connection.commit()

    def test_all_seven_conditions_are_detected_in_one_run(
        self, connection: Connection, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        """Together, because a detector that only works in isolation is a detector
        that reports nothing on a real bucket."""

        self.seed_every_condition(connection, storage, tmp_path)

        findings = detect_all(connection, storage, now=NOW)

        assert {finding.condition for finding in findings} == set(CONDITIONS)

    def test_no_row_and_no_object_disappears(
        self, connection: Connection, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        self.seed_every_condition(connection, storage, tmp_path)

        def counts() -> tuple[int, int, list[str]]:
            files = connection.execute(text("SELECT count(*) FROM file_objects")).scalar_one()
            jobs = connection.execute(text("SELECT count(*) FROM processing_jobs")).scalar_one()
            return files, jobs, sorted(storage.iter_keys())

        before = counts()
        detect_all(connection, storage, now=NOW)
        after = counts()

        assert after == before

    def test_detection_succeeds_as_a_role_that_holds_no_delete_privilege(
        self, provisioned_database: RuntimeIdentities, tmp_path: Path
    ) -> None:
        """The independent check.

        Row counts prove nothing deleted *this time*; running as the app role — which
        20260801_0011 grants UPDATE without DELETE — proves the code could not delete
        even if it tried. A DELETE would raise InsufficientPrivilege and fail the run.
        """

        result = run_alembic(
            provisioned_database.migrator_url,
            "upgrade",
            "head",
            app_role=provisioned_database.app_role,
            worker_role=provisioned_database.worker_role,
        )
        assert result.returncode == 0, result.stderr

        storage = LocalStorageBackend(tmp_path / "objects")
        storage.check_available()
        store(storage, "bank_receipt/2026/08/06/orphan", OTHER.content)

        engine = create_engine(_sqlalchemy_url(provisioned_database.app_url), future=True)
        try:
            with engine.connect() as conn:
                conn.execution_options(isolation_level="AUTOCOMMIT")
                findings = detect_all(conn, storage, now=NOW)
        finally:
            engine.dispose()

        assert [f.condition for f in findings] == ["storage_object_without_a_record"]
        assert sorted(storage.iter_keys()) == ["bank_receipt/2026/08/06/orphan"]

    def test_a_clean_system_produces_no_findings(
        self, connection: Connection, storage: LocalStorageBackend
    ) -> None:
        """Guard the guard. If `detect_all` reported findings on a consistent
        system, every assertion above would pass for the wrong reason."""

        key = "bank_receipt/2026/08/06/consistent"
        store(storage, key, RECEIPT.content)
        record_file(connection, key=key, sha256=RECEIPT.sha256, size=RECEIPT.size_bytes)

        assert detect_all(connection, storage, now=NOW) == []
