"""The restore drill. §20.5: "backup and full restore drill pass", and the line after it.

M12 slice 2.

**A backup nobody has restored is a belief.** The exit gate does not ask for a backup script — it
asks for a drill, and then asks that "restored files, approvals, publications, and audit records
reconcile". This is that drill, run against a real PostgreSQL rather than described in a runbook.

## The shape

1. Build a world with rows in every table §20.5 names, and files on disk.
2. Record a manifest of what is there.
3. Back it up.
4. Restore into a **second, clean** database and a **second, empty** storage tree.
5. Build a manifest of the restored side and compare.

**Step 4 is the whole design.** Restoring over the source proves nothing: every row the manifest
expects is already present, so the comparison passes whether or not the dump contained anything.
`restore.sh` refuses a non-empty target for exactly that reason, and
`test_the_restore_refuses_a_database_that_already_has_rows` asserts the refusal rather than
trusting it.

## Why the manifest is not just counts

A restore can produce the right number of rows and the wrong contents — a dump taken mid
transaction, a storage copy that truncated. Every table carries a digest over its identifying
columns, and the storage tree carries a digest of the **bytes on disk** rather than of the
database's record of them. A check that compared `file_objects.sha256_hash` against itself would
agree with itself while both sides were wrong.

Covers: OPS-BACKUP-001, OPS-BACKUP-002.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPOSITORY_ROOT / "infra" / "scripts"

# **There is no container name here, and an earlier version had one.** It was `m2-itest-pg`, which
# is what this machine calls its integration database — and CI names its service containers
# differently, so the drill failed there with `No such container` after passing locally. The name
# was an *environment* fact wearing the shape of a design decision.
#
# Everything below works from the database URL the suite is already given, which is the only thing
# both environments agree on. `postgres:16.14-alpine3.24` supplies `psql` and `createdb`: matched to
# the server, because `pg_dump` refuses a server newer than itself.
PG_IMAGE = "postgres:16.14-alpine3.24"


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def _manifest_module() -> Any:
    """Import the manifest builder the scripts use, rather than reimplementing it.

    The drill and `backup.sh` must agree on *what* is recorded. Two implementations would drift,
    and the drill would then reconcile a manifest nobody takes in production.
    """

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "backup_manifest", SCRIPTS / "backup_manifest.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def drill(provisioned_database: RuntimeIdentities, tmp_path: Path) -> Iterator[dict[str, Any]]:
    """A migrated source database with rows, files on disk, and a clean target to restore into."""

    result = run_alembic(
        provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=provisioned_database.app_role,
        worker_role=provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    source_name = _database_name(provisioned_database.migrator_url)
    target_name = f"{source_name}_restored"[:63]
    maintenance = _admin_url(provisioned_database.migrator_url, "postgres")

    _run_psql(f'CREATE DATABASE "{target_name}"', maintenance)

    storage = tmp_path / "storage"
    restored_storage = tmp_path / "restored-storage"
    storage.mkdir()

    yield {
        "identities": provisioned_database,
        "source": source_name,
        "target": target_name,
        "storage": storage,
        "restored_storage": restored_storage,
        "out": tmp_path / "backups",
    }

    _run_psql(f'DROP DATABASE IF EXISTS "{target_name}"', maintenance)


def _database_name(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


def _admin_url(source_url: str, database: str) -> str:
    """The same server, a different database, as `postgres`.

    `postgres` rather than the migration role because creating and dropping a database needs
    `CREATEDB`, and because `pg_restore --no-owner` will leave the restored objects owned by
    whoever connects — see `_restored_url`.
    """

    host_and_port = source_url.split("@", 1)[1].rsplit("/", 1)[0]
    return f"postgresql://postgres:postgres@{host_and_port}/{database}"


def _run_psql(command: str, url: str) -> str:
    completed = subprocess.run(
        [
            "docker", "run", "--rm", "--network", "host", PG_IMAGE,
            "psql", url, "--no-align", "--tuples-only", "--command", command,
        ],
        check=True, capture_output=True, text=True,
    )
    return completed.stdout


def _seed(world: dict[str, Any]) -> None:
    """Rows in every table the exit gate names, and bytes on disk to go with them.

    Deliberately small and deliberately *not* empty: a drill over an empty database reconciles
    trivially, which is the vacuous pass this whole file exists to avoid.
    """

    url = world["identities"].migrator_url
    admin_id = uuid.uuid4()
    file_id = uuid.uuid4()

    with psycopg.connect(_psycopg(url)) as connection:
        connection.execute(
            "INSERT INTO admin_users (id, username, full_name, password_hash, status) "
            "VALUES (%s, 'drill_admin', 'Drill', 'x', 'active')",
            (admin_id,),
        )
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, 'receipt.pdf', 'application/pdf', 11, %s, "
            "'bank_result_bundle_source', 'internal', 'available', 'clean', 'admin_user', "
            "'original', '{}')",
            (file_id, f"drill/{file_id}", "d" * 64),
        )
        connection.commit()

    # The bytes the row above claims to describe. A backup that took the database and not these
    # would restore a system that can name evidence it cannot show.
    stored = world["storage"] / "drill"
    stored.mkdir(parents=True, exist_ok=True)
    (stored / str(file_id)).write_bytes(b"drill bytes")
    (stored / "second.bin").write_bytes(b"a second file, so a one-file copy is not enough")


def _build_manifest(url: str, storage: Path) -> dict[str, Any]:
    module = _manifest_module()
    with psycopg.connect(_psycopg(url)) as connection:
        return module.build(connection, storage)


def _restored_url(source_url: str, target: str) -> str:
    """The restored database, read as the role that restored it.

    **`pg_restore --no-owner` leaves every object owned by the restoring role**, so connecting as
    the migration role — which owns the *source* — answers `permission denied for table
    file_objects`. That is what `--no-owner` means rather than a defect in the restore: a real
    recovery hands ownership and grants back afterwards, which is slice 4's runbook step.

    Reading as `postgres` keeps this drill about whether the **data** survived. Whether the grants
    survived is a different question, and one this file should not answer quietly by connecting as
    a role that happens to work.
    """

    host_and_port = source_url.split("@", 1)[1].rsplit("/", 1)[0]
    return f"postgresql+psycopg://postgres:postgres@{host_and_port}/{target}"


def _backup(world: dict[str, Any]) -> Path:
    source_url = _admin_url(world["identities"].migrator_url, world["source"])
    completed = subprocess.run(
        [
            "bash", str(SCRIPTS / "backup.sh"),
            "--database-url", source_url,
            "--storage", str(world["storage"]),
            "--out", str(world["out"]),
        ],
        cwd=REPOSITORY_ROOT, capture_output=True, text=True,
    )
    assert completed.returncode == 0, (
        f"backup.sh failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )

    bundles = sorted(world["out"].glob("golden-backup-*.tar"))
    assert len(bundles) == 1, f"expected one bundle, found {bundles}"
    return bundles[0]


def _restore(
    world: dict[str, Any], bundle: Path, *, force: bool = False
) -> subprocess.CompletedProcess[str]:
    arguments = [
        "bash", str(SCRIPTS / "restore.sh"),
        "--bundle", str(bundle),
        "--database-url", _admin_url(world["identities"].migrator_url, world["target"]),
        "--storage", str(world["restored_storage"]),
    ]
    if force:
        arguments.append("--force")
    return subprocess.run(arguments, cwd=REPOSITORY_ROOT, capture_output=True, text=True)


def test_a_backup_restores_into_a_clean_database_and_reconciles(drill: dict[str, Any]) -> None:
    """§20.5's exit condition, end to end.

    **The assertion is the reconciliation, not the exit code.** A restore that ran is not a restore
    that is correct — `pg_restore` exits zero having skipped objects it could not create, and a
    drill that checked only the exit code would pass over exactly that.
    """

    _seed(drill)

    source_url = drill["identities"].migrator_url
    expected = _build_manifest(source_url, drill["storage"])

    # The premise, asserted rather than assumed: a manifest over an empty database reconciles with
    # anything, so a drill built on one proves nothing.
    assert expected["tables"]["file_objects"]["rows"] > 0
    assert expected["storage"]["files"] == 2

    bundle = _backup(drill)
    completed = _restore(drill, bundle)
    assert completed.returncode == 0, (
        f"restore.sh failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )

    target_url = _restored_url(source_url, drill["target"])
    actual = _build_manifest(target_url, drill["restored_storage"])

    problems = _manifest_module().compare(expected, actual)
    assert problems == [], "the restore does not reconcile:\n" + "\n".join(problems)


def test_the_restore_refuses_a_database_that_already_has_rows(drill: dict[str, Any]) -> None:
    """The refusal that makes the drill mean something.

    Restoring over a populated database is how a drill passes while proving nothing: every row the
    manifest expects is already there. It is also how a drill destroys the thing it was meant to
    protect. `--force` exists for a real recovery and is a separate word somebody has to type.
    """

    _seed(drill)
    bundle = _backup(drill)

    # Restore once into the clean target, so the target now has rows.
    first = _restore(drill, bundle)
    assert first.returncode == 0, first.stderr

    # **The storage tree is emptied first, and a negative control is why.** `restore.sh` refuses a
    # non-empty *storage directory* as well as a non-empty database, and after the first restore
    # both are non-empty. A control that removed the database check entirely was NOT CAUGHT,
    # because the storage refusal fired instead and the test could not tell the two apart — it
    # asserted "something refused", which is not the claim in its name.
    for path in sorted(drill["restored_storage"].rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()

    second = _restore(drill, bundle)

    assert second.returncode != 0, (
        "restore.sh overwrote a database that already had rows without being forced"
    )
    assert "rows" in second.stderr.lower(), (
        "something refused, but not the database check — this test exists to assert *that* "
        f"refusal, and the message was: {second.stderr}"
    )


def test_a_lost_table_is_reported_rather_than_passed_over(drill: dict[str, Any]) -> None:
    """The manifest comparison, provoked directly.

    **This is the control the drill above cannot be.** That test passes when everything works, which
    is also what it would do if `compare` returned an empty list for every input. Here a row is
    deleted from the restored side and the comparison is required to name the table.
    """

    _seed(drill)

    source_url = drill["identities"].migrator_url
    expected = _build_manifest(source_url, drill["storage"])

    bundle = _backup(drill)
    assert _restore(drill, bundle).returncode == 0

    target_url = _restored_url(source_url, drill["target"])
    with psycopg.connect(_psycopg(target_url)) as connection:
        connection.execute("DELETE FROM file_objects")
        connection.commit()

    actual = _build_manifest(target_url, drill["restored_storage"])
    problems = _manifest_module().compare(expected, actual)

    assert any("file_objects" in line for line in problems), (
        f"a table lost every row and the comparison said: {problems}"
    )


def test_a_row_changed_without_changing_the_count_is_reported(drill: dict[str, Any]) -> None:
    """The digest, provoked — and **this test exists because a control was NOT CAUGHT.**

    Replacing every table digest with a constant changed nothing: the other tests here delete rows
    or empty files, so a count alone catches them, and the digest was machinery no assertion
    reached. That is the same defect this repository has found in its own guards twice before.

    The failure it now covers is the one a count cannot see and the one a restore actually has: a
    dump taken while a transaction was in flight, a column that came back with a default instead of
    its value. Same number of rows, different money.
    """

    _seed(drill)

    source_url = drill["identities"].migrator_url
    expected = _build_manifest(source_url, drill["storage"])

    bundle = _backup(drill)
    assert _restore(drill, bundle).returncode == 0

    target_url = _restored_url(source_url, drill["target"])
    with psycopg.connect(_psycopg(target_url)) as connection:
        # One column, one row, no change in count. `sha256_hash` is in the manifest's column list
        # for `file_objects`, and it is what the platform believes about a receipt's bytes.
        connection.execute("UPDATE file_objects SET sha256_hash = %s", ("f" * 64,))
        connection.commit()

    actual = _build_manifest(target_url, drill["restored_storage"])

    # The premise, asserted rather than assumed: if the counts differed, this test would pass
    # through the count check and say nothing about the digest.
    assert actual["tables"]["file_objects"]["rows"] == expected["tables"]["file_objects"]["rows"]

    problems = _manifest_module().compare(expected, actual)
    assert any("file_objects" in line for line in problems), (
        f"a row's contents changed with the count unchanged and the comparison said: {problems}"
    )


def test_a_stored_file_with_the_same_size_and_different_bytes_is_reported(
    drill: dict[str, Any],
) -> None:
    """The same claim for the half that is not in the database — **and the bytes are replaced
    rather than removed, because a control was NOT CAUGHT.**

    The first version emptied the file. That changes its *size*, so a manifest comparing sizes
    instead of content caught it too, and the test could not tell the two apart. Comparing by size
    is a real and tempting shortcut — it is much faster on a large storage tree — and it misses the
    case that matters: a copy that wrote the right number of bytes from the wrong source.

    The bytes are the evidence a payment was made. A file of the right length containing somebody
    else's receipt is worse than a file that is missing.
    """

    _seed(drill)

    source_url = drill["identities"].migrator_url
    expected = _build_manifest(source_url, drill["storage"])

    bundle = _backup(drill)
    assert _restore(drill, bundle).returncode == 0

    restored = sorted(p for p in drill["restored_storage"].rglob("*") if p.is_file())
    assert restored, "the restore produced no files, so this test asserted nothing"

    original = restored[0].read_bytes()
    replacement = bytes(byte ^ 0xFF for byte in original)
    assert len(replacement) == len(original) and replacement != original
    restored[0].write_bytes(replacement)

    target_url = _restored_url(source_url, drill["target"])
    actual = _build_manifest(target_url, drill["restored_storage"])

    # The premise: the file count and the total byte count are both unchanged, so anything the
    # comparison reports came from the content digest.
    assert actual["storage"]["files"] == expected["storage"]["files"]
    assert actual["storage"]["bytes"] == expected["storage"]["bytes"]

    problems = _manifest_module().compare(expected, actual)

    assert any("storage" in line for line in problems), (
        f"a stored file's bytes changed with its size unchanged and the comparison said: {problems}"
    )


def test_the_bundle_carries_all_three_parts(drill: dict[str, Any]) -> None:
    """Database, storage and manifest. A bundle missing one is a bundle that restores a lie."""

    _seed(drill)
    bundle = _backup(drill)

    listed = subprocess.run(
        ["tar", "--list", "--file", str(bundle)], check=True, capture_output=True, text=True
    ).stdout.split()

    assert set(listed) == {"database.dump", "storage.tar.gz", "manifest.json"}, listed

    # And the digest beside it, so a corrupted transfer is detectable before a restore is attempted
    # rather than after it half-succeeds.
    assert bundle.with_suffix(".tar.sha256").exists() or Path(
        str(bundle) + ".sha256"
    ).exists(), "no sha256 was written beside the bundle"


def test_the_manifest_inside_the_bundle_matches_the_source(drill: dict[str, Any]) -> None:
    """`backup.sh` builds its manifest through `docker exec psql`; the drill builds one through
    psycopg. **Both must agree**, or the manifest an operator reconciles against in production is
    not the one this drill validates.

    This is the assertion that keeps the runbook path and the tested path the same path.
    """

    _seed(drill)
    expected = _build_manifest(drill["identities"].migrator_url, drill["storage"])
    bundle = _backup(drill)

    extracted = drill["out"] / "unpacked"
    extracted.mkdir()
    subprocess.run(
        ["tar", "--extract", "--file", str(bundle), "--directory", str(extracted)],
        check=True, capture_output=True,
    )
    from_bundle = json.loads((extracted / "manifest.json").read_text(encoding="utf-8"))

    problems = _manifest_module().compare(expected, from_bundle)
    assert problems == [], (
        "the manifest backup.sh wrote disagrees with the one this test builds, so the two read the "
        "database differently:\n" + "\n".join(problems)
    )

    shutil.rmtree(extracted)
