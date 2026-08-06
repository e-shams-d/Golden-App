"""The storage contract, exercised against a real filesystem.

OPS-STORAGE-001 is the first class and the most important one: `check_available`
and the readiness probe must behave exactly as they did before the protocol grew.
An extension that changes what `/health/ready` reports is not an extension, and it
would be invisible in review because the diff only adds methods.

Everything else here is about the three properties the added methods promise —
containment, atomicity, and measurement in the same pass as the write.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import io
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.observability.health import storage_probe
from app.storage.interface import StorageBackend, StorageError, StorageKeyError, StoredObject
from app.storage.keys import InvalidStorageCategoryError, generate_storage_key
from app.storage.local import LocalStorageBackend
from file_fixtures import FIXTURES_BY_NAME


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(tmp_path / "objects")


class TestTheM1ContractIsUnchanged:
    """OPS-STORAGE-001. The probe binds to `check_available`; it must not have moved."""

    def test_the_backend_still_satisfies_the_protocol(self, storage: LocalStorageBackend) -> None:
        assert isinstance(storage, StorageBackend)

    def test_check_available_creates_the_root_and_returns_none(self, tmp_path: Path) -> None:
        root = tmp_path / "not-yet"
        backend = LocalStorageBackend(root)

        assert backend.check_available() is None
        assert root.is_dir()

    def test_check_available_leaves_no_probe_file_behind(
        self, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        storage.check_available()
        storage.check_available()

        assert list((tmp_path / "objects").iterdir()) == []

    def test_check_available_raises_when_the_root_is_a_file(self, tmp_path: Path) -> None:
        occupied = tmp_path / "occupied"
        occupied.write_bytes(b"not a directory")

        with pytest.raises(OSError):
            LocalStorageBackend(occupied).check_available()

    def test_the_readiness_probe_still_reports_healthy(self, storage: LocalStorageBackend) -> None:
        """Through the probe rather than the method, because the probe is what
        readiness actually calls.

        `asyncio.run` rather than an async test: no async plugin is configured, and
        `--strict-markers` would turn an `anyio` marker into a collection error.
        """

        result = asyncio.run(storage_probe(storage, timeout_seconds=2.0).check())

        # `"ok"` is the exact string `HealthService` compares against for readiness,
        # so this asserts the value readiness actually depends on rather than a
        # convenience flag.
        assert result.status == "ok"
        assert result.error_code is None


class TestKeysAreConfinedToTheRoot:
    """A key that escapes the root lets one upload read or overwrite another."""

    @pytest.mark.parametrize(
        "key",
        [
            "../escape",
            "a/../../escape",
            "/absolute/path",
            "windows\\path",
            "C:/drive",
            "trailing/",
            "double//slash",
            ".",
            "..",
            " leading-space",
            "",
        ],
    )
    def test_a_hostile_key_is_refused(self, storage: LocalStorageBackend, key: str) -> None:
        with pytest.raises(StorageKeyError):
            storage.write(key, io.BytesIO(b"payload"))

    def test_a_refused_key_writes_nothing(
        self, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        """Guard the guard: refusing after writing would be no protection at all."""

        storage.check_available()
        with pytest.raises(StorageKeyError):
            storage.write("../escaped", io.BytesIO(b"payload"))

        assert not (tmp_path / "escaped").exists()
        assert list((tmp_path / "objects").rglob("*")) == []

    def test_a_key_traversing_a_symlink_out_of_the_root_is_refused(
        self, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        """The only case the resolved-path check catches and a string check cannot.

        A negative control exposed this gap: every hostile key above is rejected by
        the string checks before the resolved path is ever compared, so the
        containment check was untested and could have been deleted without a single
        failure. `outside/loot` contains no `..`, no leading slash and no backslash —
        it is an ordinary-looking relative key whose first segment happens to be a
        symlink pointing at somebody else's directory.
        """

        root = tmp_path / "objects"
        root.mkdir(parents=True, exist_ok=True)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        try:
            (root / "outside").symlink_to(elsewhere, target_is_directory=True)
        except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
            pytest.skip("this platform does not permit creating a symlink")

        with pytest.raises(StorageKeyError, match="outside the storage root"):
            storage.write("outside/loot", io.BytesIO(b"payload"))

        assert list(elsewhere.iterdir()) == []

    def test_a_symlinked_key_is_refused_on_read_as_well_as_write(
        self, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        """Reading through the symlink is the exfiltration half of the same hole."""

        root = tmp_path / "objects"
        root.mkdir(parents=True, exist_ok=True)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "secret").write_bytes(b"another tenant's receipt")
        try:
            (root / "outside").symlink_to(elsewhere, target_is_directory=True)
        except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
            pytest.skip("this platform does not permit creating a symlink")

        with pytest.raises(StorageKeyError):
            storage.stat("outside/secret")
        with pytest.raises(StorageKeyError), storage.open("outside/secret"):
            pass

    def test_an_ordinary_nested_key_is_accepted(self, storage: LocalStorageBackend) -> None:
        stored = storage.write("receipt/2026/08/06/abc123", io.BytesIO(b"payload"))

        assert stored.size_bytes == 7


class TestWriteMeasuresWhatItWrote:
    def test_the_digest_and_size_match_the_content(self, storage: LocalStorageBackend) -> None:
        payload = b"a bank receipt, notionally"

        stored = storage.write("k/1", io.BytesIO(payload))

        assert stored.sha256_hash == hashlib.sha256(payload).hexdigest()
        assert stored.size_bytes == len(payload)

    def test_an_empty_object_is_written_and_measured(self, storage: LocalStorageBackend) -> None:
        """Zero bytes is a real upload, and `size_bytes >= 0` in the schema exists
        for it. The digest of nothing is still a digest."""

        stored = storage.write("k/empty", io.BytesIO(b""))

        assert stored.size_bytes == 0
        assert stored.sha256_hash == hashlib.sha256(b"").hexdigest()

    def test_content_larger_than_one_chunk_hashes_correctly(
        self, storage: LocalStorageBackend
    ) -> None:
        """The chunk loop is where an off-by-one would live, and a payload smaller
        than one chunk would never exercise it."""

        payload = bytes(range(256)) * 4096  # 1 MiB, four chunks

        stored = storage.write("k/large", io.BytesIO(payload))

        assert stored.size_bytes == len(payload)
        assert stored.sha256_hash == hashlib.sha256(payload).hexdigest()

    def test_writing_twice_to_one_key_is_refused(self, storage: LocalStorageBackend) -> None:
        """Overwriting would replace content whose digest another row records: the
        row still verifies, against different bytes."""

        storage.write("k/once", io.BytesIO(b"first"))

        with pytest.raises(StorageError):
            storage.write("k/once", io.BytesIO(b"second"))

    def test_the_first_content_survives_a_refused_overwrite(
        self, storage: LocalStorageBackend
    ) -> None:
        storage.write("k/once", io.BytesIO(b"first"))
        with pytest.raises(StorageError):
            storage.write("k/once", io.BytesIO(b"second"))

        with storage.open("k/once") as handle:
            assert handle.read() == b"first"

    def test_nothing_is_visible_at_the_key_until_the_write_completes(
        self, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        """Atomicity as a reader experiences it, which is the only way it matters.

        A negative control exposed that the tests below prove *cleanup on failure*,
        not atomicity: writing straight to the target and skipping the rename left
        them green, because the error path deleted the target anyway. The difference
        only shows from inside the write, so this observes the key half way through.

        A partial object a reader can open is one that gets hashed, recorded and
        treated as evidence.
        """

        key = "k/observed"
        target = tmp_path / "objects" / key
        payload = b"first half" + b"second half"
        observed: dict[str, object] = {}

        class HalfwayObserver(io.RawIOBase):
            """Yields two chunks, reporting what a reader would see between them."""

            def __init__(self) -> None:
                self._chunks = [payload[:10], payload[10:]]
                self._index = 0

            def readable(self) -> bool:
                return True

            def read(self, size: int = -1) -> bytes:
                if self._index == 1:
                    observed["stat"] = storage.stat(key)
                    observed["target_exists"] = target.exists()
                if self._index >= len(self._chunks):
                    return b""
                chunk = self._chunks[self._index]
                self._index += 1
                return chunk

        stored = storage.write(key, HalfwayObserver())  # type: ignore[arg-type]

        assert observed["stat"] is None, (
            "a reader could stat the key while it was still being written, so a "
            "half-uploaded object is observable"
        )
        assert observed["target_exists"] is False
        assert stored.size_bytes == len(payload)
        assert storage.stat(key) == stored

    def test_a_failing_source_leaves_no_object(self, storage: LocalStorageBackend) -> None:
        """Cleanup on failure, which is the weaker claim of the two.

        Kept alongside the atomicity test above rather than replaced by it: this one
        covers the error path, that one covers the happy path's visibility.
        """

        class Exploding(io.RawIOBase):
            def readable(self) -> bool:
                return True

            def read(self, size: int = -1) -> bytes:
                raise OSError("the network went away")

        with pytest.raises(OSError, match="the network went away"):
            storage.write("k/partial", Exploding())  # type: ignore[arg-type]

        assert storage.stat("k/partial") is None

    def test_a_failed_write_leaves_no_partial_file_for_reconciliation_to_find(
        self, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        """A leaked `.partial-` file would be reported as an orphaned object on
        every killed worker, and a report that cries wolf is a report nobody
        reads."""

        class Exploding(io.RawIOBase):
            def readable(self) -> bool:
                return True

            def read(self, size: int = -1) -> bytes:
                raise OSError("boom")

        with pytest.raises(OSError):
            storage.write("k/partial", Exploding())  # type: ignore[arg-type]

        assert list(storage.iter_keys()) == []
        assert list((tmp_path / "objects").rglob(".partial-*")) == []


class TestReadingBack:
    def test_open_streams_the_written_bytes(self, storage: LocalStorageBackend) -> None:
        storage.write("k/1", io.BytesIO(b"content"))

        with storage.open("k/1") as handle:
            assert handle.read() == b"content"

    def test_open_closes_the_handle_on_exit(self, storage: LocalStorageBackend) -> None:
        storage.write("k/1", io.BytesIO(b"content"))

        with storage.open("k/1") as handle:
            pass

        assert handle.closed is True

    def test_opening_a_missing_key_raises(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(StorageError), storage.open("k/absent"):
            pass

    def test_stat_returns_none_for_a_missing_key(self, storage: LocalStorageBackend) -> None:
        """None rather than raising: "absent" is an ordinary reconciliation answer,
        and an exception would make the common case the expensive one."""

        assert storage.stat("k/absent") is None

    def test_stat_measures_the_same_values_write_reported(
        self, storage: LocalStorageBackend
    ) -> None:
        """The two must agree or a checksum mismatch means nothing."""

        written = storage.write("k/1", io.BytesIO(b"the same bytes"))

        assert storage.stat("k/1") == written


class TestEnumeratingForReconciliation:
    def test_keys_come_back_as_posix_relative_paths(self, storage: LocalStorageBackend) -> None:
        """Provider-independent, so a key recorded against the local adapter still
        means something after a move to object storage."""

        storage.write("receipt/2026/08/06/aaa", io.BytesIO(b"1"))
        storage.write("export/2026/08/06/bbb", io.BytesIO(b"2"))

        assert sorted(storage.iter_keys()) == [
            "export/2026/08/06/bbb",
            "receipt/2026/08/06/aaa",
        ]

    def test_health_probe_files_are_not_reported_as_objects(
        self, storage: LocalStorageBackend
    ) -> None:
        """Weak on its own, because `check_available` removes its own probe file.

        Kept because it is the ordinary path, but the case the dotfile skip actually
        exists for is the test below.
        """

        storage.check_available()
        storage.write("k/1", io.BytesIO(b"1"))

        assert list(storage.iter_keys()) == ["k/1"]

    def test_a_leftover_partial_file_is_not_reported_as_an_object(
        self, storage: LocalStorageBackend, tmp_path: Path
    ) -> None:
        """The case the dotfile skip is really for: a worker killed mid-write.

        A negative control exposed that the test above passes whether or not
        `iter_keys` skips dotfiles, because both `check_available` and `write` clean
        up after themselves — so nothing was ever there to skip. What leaves a
        `.partial-` file behind is SIGKILL, which runs no cleanup at all. Simulated
        by creating the file directly, because that is exactly the state a killed
        process leaves.

        Reporting it would make reconciliation flag an orphaned object on every
        killed worker, and a report that cries wolf is a report nobody reads.
        """

        root = tmp_path / "objects"
        (root / "k").mkdir(parents=True, exist_ok=True)
        storage.write("k/1", io.BytesIO(b"1"))
        (root / "k" / ".partial-abc123").write_bytes(b"half an upload")
        (root / ".health-xyz789").write_bytes(b"storage-health")

        assert list(storage.iter_keys()) == ["k/1"]

    def test_an_absent_root_enumerates_empty_rather_than_raising(self, tmp_path: Path) -> None:
        assert list(LocalStorageBackend(tmp_path / "never-created").iter_keys()) == []


class TestStoredObjectRefusesImpossibleValues:
    def test_a_negative_size_is_refused(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            StoredObject(size_bytes=-1, sha256_hash="a" * 64)

    @pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "", "not-a-digest"])
    def test_a_digest_the_database_would_reject_is_refused_here_first(self, digest: str) -> None:
        """The same shape as `ck_file_objects_sha256_is_lowercase_hex`.

        Refusing here means the failure names the storage layer that produced the
        bad value, rather than surfacing as a constraint violation three call frames
        later.
        """

        with pytest.raises(ValueError, match="64 lower-case hex"):
            StoredObject(size_bytes=1, sha256_hash=digest)


class TestGeneratedKeysAreOpaque:
    MOMENT = datetime(2026, 8, 6, 22, 30, tzinfo=UTC)

    def test_the_shape_is_category_date_and_random(self) -> None:
        key = generate_storage_key(category="bank_receipt", moment=self.MOMENT)

        prefix, year, month, day, random_part = key.split("/")

        assert (prefix, year, month, day) == ("bank_receipt", "2026", "08", "06")
        assert len(random_part) == 32

    def test_two_keys_for_the_same_moment_differ(self) -> None:
        """128 bits from `secrets`, so knowing one key tells an attacker nothing
        about the next."""

        keys = {generate_storage_key(category="c", moment=self.MOMENT) for _ in range(200)}

        assert len(keys) == 200

    def test_the_partition_is_utc_not_local(self) -> None:
        """22:30 UTC is the next day in Tehran. Both callers must land in the same
        folder, or an operator scanning a day's partition misses files."""

        tehran = timezone(timedelta(hours=3, minutes=30))
        from_utc = generate_storage_key(category="c", moment=self.MOMENT)
        from_tehran = generate_storage_key(category="c", moment=self.MOMENT.astimezone(tehran))

        assert from_utc.rsplit("/", 1)[0] == from_tehran.rsplit("/", 1)[0]

    def test_a_naive_moment_is_refused(self) -> None:
        with pytest.raises(ValueError):
            generate_storage_key(category="c", moment=datetime(2026, 8, 6, 22, 30))

    @pytest.mark.parametrize(
        "category", ["../escape", "Bank_Receipt", "with space", "", "9leading", "a" * 41]
    )
    def test_a_category_that_is_not_a_safe_segment_is_refused(self, category: str) -> None:
        with pytest.raises(InvalidStorageCategoryError):
            generate_storage_key(category=category, moment=self.MOMENT)

    @pytest.mark.parametrize(
        "fixture_name", ["filename_attempting_traversal", "filename_with_control_characters"]
    )
    def test_no_part_of_a_hostile_filename_reaches_the_key(self, fixture_name: str) -> None:
        """FILE-META-001's other half. The key is generated, so the filename cannot
        reach it — asserted rather than assumed, because "we sanitise it" is the
        answer that produces the next traversal bug.
        """

        fixture = FIXTURES_BY_NAME[fixture_name]

        key = generate_storage_key(category="bank_receipt", moment=self.MOMENT)

        assert ".." not in key
        assert "\x00" not in key and "\r" not in key and "\n" not in key
        for fragment in ("passwd", "receipt", "etc"):
            assert fragment not in key.split("/")[-1]
        # The structural reason rather than the observed one: the generator has no
        # parameter a filename could be passed through. Asserting the absence of the
        # channel is stronger than asserting the absence of the output.
        assert set(inspect.signature(generate_storage_key).parameters) == {
            "category",
            "moment",
        }, f"{fixture.upload_filename!r} must have no way in"

    def test_a_generated_key_is_accepted_by_the_backend(self, storage: LocalStorageBackend) -> None:
        """The two halves must fit: a generator producing keys the backend refuses
        would fail only in production."""

        key = generate_storage_key(category="bank_receipt", moment=self.MOMENT)

        assert storage.write(key, io.BytesIO(b"payload")).size_bytes == 7


class TestTheFixturesRoundTrip:
    """Every artifact must survive a write and read unchanged.

    Bytes in, same bytes out, and the digest the backend measured equal to the one
    computed from the fixture — which is what makes the checksum-mismatch detector
    trustworthy when it reports a difference.
    """

    @pytest.mark.parametrize("fixture_name", sorted(FIXTURES_BY_NAME))
    def test_content_and_digest_survive(
        self, storage: LocalStorageBackend, fixture_name: str
    ) -> None:
        fixture = FIXTURES_BY_NAME[fixture_name]

        stored = storage.write(f"k/{fixture_name}", io.BytesIO(fixture.content))
        with storage.open(f"k/{fixture_name}") as handle:
            read_back = handle.read()

        assert read_back == fixture.content
        assert stored.sha256_hash == fixture.sha256
        assert stored.size_bytes == fixture.size_bytes
