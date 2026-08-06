"""File metadata against the real database. The constraints, not the conventions.

Three properties carry this slice, and every one of them is a rule doc 04 states
in prose and supplies no constraint for — which is exactly the kind of rule that
survives review and then quietly stops holding:

  - a file cannot be `available` without a checksum
  - a file cannot be `available` unless its scan came back clean
  - a derivation cannot exist twice for the same source, type, parameters and
    renderer

The third is the one that decides whether a crop is reproducible. Asserted over a
canonical `parameters_hash` rather than raw JSONB, because a JSONB unique index
calls two identical derivations different whenever a dict serialises in another
order — and the failure would appear as a duplicate crop months later, not here.

The introspection tests at the end are DB-FILE-001: they read `information_schema`
and `pg_indexes` rather than the model, because the model is what we meant and the
database is what we got.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
PARAMETERS_HASH = f"v1:{'c' * 64}"


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_psycopg(migrated_database), autocommit=True) as conn:
        try:
            yield conn
        finally:
            # Derivations and links reference objects, so they go first.
            for table in ("file_derivations", "file_links", "file_objects"):
                conn.execute(f"DELETE FROM {table}")


def insert_file(
    connection: psycopg.Connection,
    *,
    key: str | None = None,
    status: str = "pending",
    scan: str = "pending",
    sha256: str | None = None,
    size: int = 1024,
    relation: str = "original",
    **overrides: object,
) -> uuid.UUID:
    """Insert one file object, defaulting to the state a fresh upload is in.

    Defaults matter here: a newly uploaded file is `pending` with no checksum, and
    a helper that defaulted to `available` with a hash would make every test set up
    the state the constraints are about rather than reach it.
    """

    columns: dict[str, object] = {
        "storage_provider": "local",
        "storage_bucket": "uploads",
        "storage_key": key or f"2026/08/{uuid.uuid4().hex}",
        "original_filename": "رسید-بانکی.pdf",
        "mime_type_declared": "application/pdf",
        "size_bytes": size,
        "sha256_hash": sha256,
        "category": "bank_receipt",
        "visibility_scope": "internal",
        "storage_status": status,
        "scan_status": scan,
        "uploaded_by_actor_type": "trader_user",
        "uploaded_by_actor_id": uuid.uuid4(),
        "original_or_derived_relation": relation,
    }
    columns.update(overrides)
    names = ", ".join(columns)
    placeholders = ", ".join(f"%({name})s" for name in columns)
    row = connection.execute(
        f"INSERT INTO file_objects ({names}) VALUES ({placeholders}) RETURNING id", columns
    ).fetchone()
    assert row is not None
    return row[0]


class TestAvailabilityRequiresAChecksum:
    """FILE-META-002. Doc 04 says "required before available" and gives no CHECK."""

    def test_a_pending_file_needs_no_hash(self, connection: psycopg.Connection) -> None:
        """Guard the guard: the checksum arrives after the bytes are read, so
        requiring it unconditionally would make an upload impossible to record."""

        assert insert_file(connection) is not None

    def test_available_without_a_hash_is_refused(self, connection: psycopg.Connection) -> None:
        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            insert_file(connection, status="available", scan="clean", sha256=None)

        assert "available_requires_hash" in str(raised.value)

    def test_available_with_a_hash_and_a_clean_scan_is_accepted(
        self, connection: psycopg.Connection
    ) -> None:
        assert insert_file(connection, status="available", scan="clean", sha256=DIGEST) is not None

    def test_transitioning_to_available_without_a_hash_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        """The path that actually happens. The insert is fine; it is the UPDATE
        four seconds later that would otherwise publish an unverifiable file."""

        file_id = insert_file(connection, scan="clean")

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute(
                "UPDATE file_objects SET storage_status = 'available' WHERE id = %s", (file_id,)
            )

        assert "available_requires_hash" in str(raised.value)

    def test_a_non_hex_checksum_is_refused(self, connection: psycopg.Connection) -> None:
        """An uppercase or truncated digest compares unequal to a correctly
        computed one, so a mismatch would read as tampering."""

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            insert_file(connection, sha256="A" * 64)

        assert "sha256_is_lowercase_hex" in str(raised.value)


class TestAvailabilityRequiresACleanScan:
    """FILE-META-003, and the reason no `scan_status` enum ships.

    ADR-008's safe default is never to treat an unchecked file as available
    evidence. Enforced at the database boundary, so it holds for a psql session and
    a background worker as much as for the upload route.
    """

    @pytest.mark.parametrize(
        "scan",
        ["pending", "quarantined", "failed", "skipped_by_approved_policy", "anything_new"],
    )
    def test_available_with_an_unclean_scan_is_refused(
        self, connection: psycopg.Connection, scan: str
    ) -> None:
        """Including a value nobody has enumerated. That is the whitelist paying
        off: a scanner version that invents an outcome fails closed."""

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            insert_file(connection, status="available", scan=scan, sha256=DIGEST)

        assert "available_requires_clean_scan" in str(raised.value)

    def test_an_unclean_scan_is_still_recordable_in_any_other_state(
        self, connection: psycopg.Connection
    ) -> None:
        """The reserved value is recorded, not refused.

        A schema that cannot store "the scanner skipped this" forces the caller to
        write something else, and the truth of what happened is what a later
        investigation needs.
        """

        file_id = insert_file(
            connection, status="quarantined", scan="skipped_by_approved_policy", sha256=DIGEST
        )

        row = connection.execute(
            "SELECT scan_status FROM file_objects WHERE id = %s", (file_id,)
        ).fetchone()

        assert row is not None and row[0] == "skipped_by_approved_policy"

    def test_scan_status_accepts_an_unenumerated_value(
        self, connection: psycopg.Connection
    ) -> None:
        """DOC-CONFLICT-029 and ADR-008 are Open, so the column constrains nothing.

        If this test starts failing, somebody added the enum and decided both.
        """

        assert insert_file(connection, scan="a_value_no_document_lists") is not None


class TestStorageStatus:
    """The recorded reconciliation, at the database boundary."""

    @pytest.mark.parametrize(
        "status",
        [
            "pending",
            "quarantined",
            "processing_failed",
            "archived",
            "retention_pending",
            "deleted",
        ],
    )
    def test_each_permitted_status_is_accepted(
        self, connection: psycopg.Connection, status: str
    ) -> None:
        assert insert_file(connection, status=status) is not None

    def test_deleted_by_policy_is_refused(self, connection: psycopg.Connection) -> None:
        """Not canonicalised away — refused, because its only writer would be the
        policy-driven deletion ADR-005 blocks from existing. Permitting it later is
        a visible widening migration."""

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            insert_file(connection, status="deleted_by_policy")

        assert "storage_status" in str(raised.value)

    def test_an_invented_status_is_refused(self, connection: psycopg.Connection) -> None:
        """`availabe` is a real typo, and without the CHECK it would sit in the
        column that gates access to financial evidence."""

        with pytest.raises(psycopg.errors.CheckViolation):
            insert_file(connection, status="availabe")

    def test_claiming_physical_deletion_in_another_state_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        """A row cannot say its bytes are gone while still offering them."""

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            insert_file(
                connection,
                status="available",
                scan="clean",
                sha256=DIGEST,
                physically_deleted_at="2026-08-06 10:00:00+00",
            )

        assert "physical_deletion_implies_deleted_status" in str(raised.value)


class TestSizeAndIdentity:
    def test_an_empty_file_is_allowed(self, connection: psycopg.Connection) -> None:
        """`>= 0`, not `> 0`. Deliberately not the money convention: an empty
        upload is a real thing a caller can do, and refusing it at the database
        boundary turns a validation message into a constraint violation."""

        assert insert_file(connection, size=0) is not None

    def test_a_negative_size_is_refused(self, connection: psycopg.Connection) -> None:
        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            insert_file(connection, size=-1)

        assert "size_is_not_negative" in str(raised.value)

    def test_the_storage_address_is_unique(self, connection: psycopg.Connection) -> None:
        """FILE-META-005's other half: a duplicate object write after a retry must
        not produce two competing metadata records for one set of bytes."""

        insert_file(connection, key="2026/08/same-key")

        with pytest.raises(psycopg.errors.UniqueViolation) as raised:
            insert_file(connection, key="2026/08/same-key")

        assert "uq_file_objects_storage_location" in str(raised.value)

    def test_the_same_key_in_another_bucket_is_a_different_object(
        self, connection: psycopg.Connection
    ) -> None:
        """The unique is over the triple, because a key is only meaningful inside
        its bucket and ADR-003 leaves the provider free."""

        insert_file(connection, key="2026/08/shared")

        assert insert_file(connection, key="2026/08/shared", storage_bucket="exports") is not None

    def test_two_files_may_share_a_checksum(self, connection: psycopg.Connection) -> None:
        """FILE-META-005. The duplicate-checksum fixture must be *representable*.

        The same document uploaded twice is a real situation to detect and report,
        not invalid data to reject — rejecting it would make the reconciliation
        condition untestable and would refuse a legitimate re-upload.
        """

        insert_file(connection, status="available", scan="clean", sha256=DIGEST)

        assert insert_file(connection, status="available", scan="clean", sha256=DIGEST) is not None

    def test_a_declared_and_detected_mime_mismatch_is_representable(
        self, connection: psycopg.Connection
    ) -> None:
        """The extension/MIME-mismatch fixture. Two columns, never reconciled:
        storing one would require choosing which to keep, and both choices destroy
        the comparison the mismatch check depends on."""

        file_id = insert_file(
            connection,
            mime_type_declared="application/pdf",
            mime_type_detected="application/x-msdownload",
        )

        row = connection.execute(
            "SELECT mime_type_declared, mime_type_detected FROM file_objects WHERE id = %s",
            (file_id,),
        ).fetchone()

        assert row is not None and row[0] != row[1]


class TestDerivationReproducibility:
    """FILE-META-004. The claim that a crop can be reproduced, made structural."""

    def derive(
        self,
        connection: psycopg.Connection,
        source: uuid.UUID,
        derived: uuid.UUID,
        *,
        derivation_type: str = "crop",
        parameters_hash: str = PARAMETERS_HASH,
        renderer_version: str = "cropper-1.0.0",
        source_hash: str = DIGEST,
    ) -> uuid.UUID:
        row = connection.execute(
            "INSERT INTO file_derivations (source_file_id, derived_file_id, derivation_type, "
            "parameters_hash, renderer_version, source_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (source, derived, derivation_type, parameters_hash, renderer_version, source_hash),
        ).fetchone()
        assert row is not None
        return row[0]

    def test_a_derivation_is_recorded(self, connection: psycopg.Connection) -> None:
        source = insert_file(connection, status="available", scan="clean", sha256=DIGEST)
        derived = insert_file(connection, relation="derived")

        assert self.derive(connection, source, derived) is not None

    def test_the_same_inputs_cannot_produce_two_results(
        self, connection: psycopg.Connection
    ) -> None:
        """The reproducibility unique. Two rows here would mean the same crop has
        two different answers, and nothing would say which one was reviewed."""

        source = insert_file(connection, status="available", scan="clean", sha256=DIGEST)
        first = insert_file(connection, relation="derived")
        second = insert_file(connection, relation="derived")

        self.derive(connection, source, first)

        with pytest.raises(psycopg.errors.UniqueViolation) as raised:
            self.derive(connection, source, second)

        assert "uq_file_derivations_reproducibility" in str(raised.value)

    def test_a_different_renderer_version_is_a_different_derivation(
        self, connection: psycopg.Connection
    ) -> None:
        """Accepted deliberately: it records that the output changed because the
        code changed, which is the question an auditor asks about a re-render."""

        source = insert_file(connection, status="available", scan="clean", sha256=DIGEST)
        first = insert_file(connection, relation="derived")
        second = insert_file(connection, relation="derived")

        self.derive(connection, source, first, renderer_version="cropper-1.0.0")

        assert self.derive(connection, source, second, renderer_version="cropper-2.0.0") is not None

    def test_different_parameters_are_a_different_derivation(
        self, connection: psycopg.Connection
    ) -> None:
        source = insert_file(connection, status="available", scan="clean", sha256=DIGEST)
        first = insert_file(connection, relation="derived")
        second = insert_file(connection, relation="derived")

        self.derive(connection, source, first)

        assert self.derive(connection, source, second, parameters_hash=f"v1:{'d' * 64}") is not None

    def test_one_source_and_one_derivative_pair_only_once(
        self, connection: psycopg.Connection
    ) -> None:
        source = insert_file(connection, status="available", scan="clean", sha256=DIGEST)
        derived = insert_file(connection, relation="derived")

        self.derive(connection, source, derived)

        with pytest.raises(psycopg.errors.UniqueViolation) as raised:
            self.derive(connection, source, derived, derivation_type="preview")

        assert "uq_file_derivations_source_derived" in str(raised.value)

    def test_a_raw_json_parameters_hash_is_refused(self, connection: psycopg.Connection) -> None:
        """The constraint that keeps the canonical form canonical.

        A JSON dump here would reintroduce exactly the key-order fragility
        `parameters_hash` exists to remove, and it would do it silently — the
        uniqueness would still appear to work.
        """

        source = insert_file(connection, status="available", scan="clean", sha256=DIGEST)
        derived = insert_file(connection, relation="derived")

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            self.derive(connection, source, derived, parameters_hash='{"x": 1, "y": 2}')

        assert "parameters_hash_is_a_versioned_digest" in str(raised.value)

    def test_an_unversioned_digest_is_refused(self, connection: psycopg.Connection) -> None:
        """A bare digest cannot be compared safely against one computed later by a
        different algorithm version."""

        source = insert_file(connection, status="available", scan="clean", sha256=DIGEST)
        derived = insert_file(connection, relation="derived")

        with pytest.raises(psycopg.errors.CheckViolation):
            self.derive(connection, source, derived, parameters_hash=DIGEST)

    def test_a_file_cannot_derive_from_itself(self, connection: psycopg.Connection) -> None:
        source = insert_file(connection, status="available", scan="clean", sha256=DIGEST)

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            self.derive(connection, source, source)

        assert "derivation_is_not_self" in str(raised.value)

    def test_the_canonical_hash_helper_produces_an_accepted_value(
        self, connection: psycopg.Connection
    ) -> None:
        """The constraint and the helper must agree, or the pattern is decoration.

        Asserted with a real call rather than a hand-written literal: a change to
        the digest format that broke the constraint would otherwise pass every test
        above, all of which use literals.
        """

        from app.core.hashing import parameters_hash

        source = insert_file(connection, status="available", scan="clean", sha256=DIGEST)
        derived = insert_file(connection, relation="derived")
        computed = parameters_hash({"x": 10, "y": 20, "width": 100, "height": 50})

        assert self.derive(connection, source, derived, parameters_hash=computed) is not None


class TestAttachmentsAreSupersededNotDeleted:
    """The chain of what was attached when has to survive a replacement."""

    def test_a_role_name_is_not_an_actor_type(self, connection: psycopg.Connection) -> None:
        """`accountant` is a role; `admin_user` is what kind of thing is acting.

        Confusing the two is the likely mistake here, and it matters because an
        attachment attributed to a role rather than an identity cannot be traced to
        a person.
        """

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute(
                "INSERT INTO file_links (file_id, resource_type, resource_id, link_role, "
                "attached_by_actor_type) VALUES (%s, 'payment_request', %s, 'receipt', "
                "'accountant')",
                (insert_file(connection), uuid.uuid4()),
            )

        assert "actor_type" in str(raised.value)

    def link(
        self, connection: psycopg.Connection, file_id: uuid.UUID, resource: uuid.UUID
    ) -> uuid.UUID:
        row = connection.execute(
            "INSERT INTO file_links (file_id, resource_type, resource_id, link_role, "
            "attached_by_actor_type) VALUES (%s, 'payment_request', %s, 'receipt', "
            "'admin_user') RETURNING id",
            (file_id, resource),
        ).fetchone()
        assert row is not None
        return row[0]

    def test_a_link_is_recorded(self, connection: psycopg.Connection) -> None:
        file_id = insert_file(connection)

        assert self.link(connection, file_id, uuid.uuid4()) is not None

    def test_a_replacement_without_a_successor_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        """A replacement that does not say what replaced it is a deletion with
        extra steps, and the history it destroys is which document was attached at
        approval time."""

        file_id = insert_file(connection)
        link = self.link(connection, file_id, uuid.uuid4())

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute("UPDATE file_links SET replaced_at = now() WHERE id = %s", (link,))

        assert "replacement_fields_move_together" in str(raised.value)

    def test_a_complete_replacement_keeps_both_rows(self, connection: psycopg.Connection) -> None:
        resource = uuid.uuid4()
        original = self.link(connection, insert_file(connection), resource)
        successor = self.link(connection, insert_file(connection), resource)

        connection.execute(
            "UPDATE file_links SET replaced_at = now(), replaced_by_file_link_id = %s "
            "WHERE id = %s",
            (successor, original),
        )

        total = connection.execute("SELECT count(*) FROM file_links").fetchone()
        active = connection.execute(
            "SELECT count(*) FROM file_links WHERE replaced_at IS NULL"
        ).fetchone()

        assert total is not None and total[0] == 2
        assert active is not None and active[0] == 1

    def test_a_link_cannot_replace_itself(self, connection: psycopg.Connection) -> None:
        link = self.link(connection, insert_file(connection), uuid.uuid4())

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute(
                "UPDATE file_links SET replaced_at = now(), replaced_by_file_link_id = id "
                "WHERE id = %s",
                (link,),
            )

        assert "replacement_is_not_self" in str(raised.value)


class TestWhatTheDatabaseActuallyBuilt:
    """DB-FILE-001, read from the catalogue rather than from the model."""

    def test_size_bytes_permits_zero_not_only_positive(
        self, connection: psycopg.Connection
    ) -> None:
        """Read as text, because the difference between `>= 0` and `> 0` is one
        character and it decides whether an empty upload can be recorded."""

        row = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_file_objects_size_is_not_negative'"
        ).fetchone()

        assert row is not None
        assert ">= 0" in row[0]

    @pytest.mark.parametrize(
        "index_name",
        [
            "idx_file_objects_hash",
            "idx_file_objects_status_category",
            "idx_file_links_active",
            "idx_file_derivations_source",
        ],
    )
    def test_the_doc_04_index_names_exist_verbatim(
        self, connection: psycopg.Connection, index_name: str
    ) -> None:
        """Named as the document names them, so an index this codebase creates and
        one a reviewer looks for are the same index."""

        row = connection.execute(
            "SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = %s",
            (index_name,),
        ).fetchone()

        assert row is not None, f"{index_name} is missing"

    def test_the_active_links_index_is_partial(self, connection: psycopg.Connection) -> None:
        row = connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_file_links_active'"
        ).fetchone()

        assert row is not None
        assert "replaced_at IS NULL" in row[0]

    @pytest.mark.parametrize("table", ["file_objects", "file_links", "file_derivations"])
    def test_no_table_carries_a_soft_delete_column(
        self, connection: psycopg.Connection, table: str
    ) -> None:
        """DB-FILE-001's last clause. Asked of the database, so a column added by a
        migration that never touched a model is caught too."""

        rows = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "AND column_name IN ('deleted_at', 'is_deleted', 'deleted', 'removed_at')",
            (table,),
        ).fetchall()

        assert rows == []


class TestTheRuntimeGrantsAreNarrow:
    """The first tables in this schema where DELETE is withheld from a mutable one.

    Connected as the app and worker roles rather than the owner: run as owner every
    assertion here passes on a database with no grants at all.
    """

    @pytest.fixture
    def migrated_as_migrator(self, provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
        result = run_alembic(
            provisioned_database.migrator_url,
            "upgrade",
            "head",
            app_role=provisioned_database.app_role,
            worker_role=provisioned_database.worker_role,
        )
        assert result.returncode == 0, (
            f"migration failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        return provisioned_database

    def test_file_objects_and_links_are_updatable_but_not_deletable(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """A file transitions through states, so UPDATE. Nothing should remove the
        record that an upload happened, so no DELETE."""

        with psycopg.connect(migrated_as_migrator.app_url) as connection:
            row = connection.execute(
                "SELECT has_table_privilege('file_objects', 'UPDATE'), "
                "has_table_privilege('file_objects', 'DELETE'), "
                "has_table_privilege('file_links', 'UPDATE'), "
                "has_table_privilege('file_links', 'DELETE')"
            ).fetchone()

        assert row is not None
        assert row == (True, False, True, False)

    def test_derivations_are_insert_and_read_only(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """A derivation is what a job produced from which inputs. Rewriting one
        would let two contradictory answers to the same question become one."""

        with psycopg.connect(migrated_as_migrator.app_url) as connection:
            row = connection.execute(
                "SELECT has_table_privilege('file_derivations', 'SELECT'), "
                "has_table_privilege('file_derivations', 'INSERT'), "
                "has_table_privilege('file_derivations', 'UPDATE'), "
                "has_table_privilege('file_derivations', 'DELETE')"
            ).fetchone()

        assert row is not None
        assert row == (True, True, False, False)

    def test_the_withheld_delete_is_enforced_and_not_merely_reported(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """`has_table_privilege` and the behaviour must agree.

        A privilege bit that says no while the statement succeeds would be the
        worst of both: a test suite that reports a protection nobody has.
        """

        with (
            psycopg.connect(migrated_as_migrator.app_url, autocommit=True) as connection,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute("DELETE FROM file_objects")

    def test_the_worker_can_advance_a_file_through_its_lifecycle(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """The privilege the scan-and-hash worker actually lives on."""

        with psycopg.connect(migrated_as_migrator.worker_url, autocommit=True) as connection:
            file_id = insert_file(connection)
            connection.execute(
                "UPDATE file_objects SET sha256_hash = %s, scan_status = 'clean', "
                "storage_status = 'available' WHERE id = %s",
                (DIGEST, file_id),
            )
            row = connection.execute(
                "SELECT storage_status FROM file_objects WHERE id = %s", (file_id,)
            ).fetchone()

        assert row is not None and row[0] == "available"
