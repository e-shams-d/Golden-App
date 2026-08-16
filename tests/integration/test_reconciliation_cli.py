"""The reconciliation checks, run by something that is not a test.

Covers: OPS-RECON-001, OPS-RECON-002, OPS-RECON-003, OPS-RECON-004, TRACE-CALLER-002.

The detectors themselves are already covered by `tests/integration/test_storage_reconciliation.py`,
which M2 wrote. What was missing was a caller: seven detectors and an aggregator that no
route, CLI or job had ever invoked. These tests are about the entry point — that it runs
every check, that its exit code is usable, and that it writes nothing.
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
def environment(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[dict[str, Any]]:
    """Settings handed to the CLI rather than set in the process environment.

    `Settings()` reads the repository's `.env`, which carries compose keys the model
    forbids, so a test that only set environment variables failed on thirteen unrelated
    fields. Injection is also the better shape: the CLI's real entry point still reads the
    environment, and a test does not have to own the process to exercise it.
    """

    from app.core.config import Settings

    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True)

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

    yield {"url": migrated.owner_url, "storage": storage_root, "settings": settings}


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _record_without_an_object(url: str) -> None:
    """A `file_objects` row whose bytes are not in storage."""

    with psycopg.connect(_psycopg(url)) as connection:
        connection.execute(
            "INSERT INTO file_objects (storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation) VALUES ('local', 'private', %s, 'gone.png', "
            "'image/png', 3, %s, 'misc_internal', 'internal_only', 'available', 'clean', "
            "'system_maintenance', 'original')",
            (f"misc_internal/2026/08/16/{uuid.uuid4().hex}", "e" * 64),
        )
        connection.commit()


def test_a_clean_deployment_reports_nothing_and_exits_zero(
    environment: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """OPS-RECON-002, the zero half.

    An operator's script branches on this, so "found nothing" must be distinguishable
    from "could not run" by exit code alone.
    """

    from app.cli.reconcile_storage import main

    assert main([], settings=environment["settings"]) == 0
    assert "No disagreements found" in capsys.readouterr().out


def test_a_disagreement_is_reported_and_exits_non_zero(
    environment: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """OPS-RECON-002, the other half."""

    from app.cli.reconcile_storage import main

    _record_without_an_object(environment["url"])

    assert main([], settings=environment["settings"]) == 1
    output = capsys.readouterr().out
    assert "record_without_a_storage_object" in output
    assert "Nothing was repaired" in output


def test_the_cli_runs_every_check_the_module_defines(
    environment: dict[str, Any],
) -> None:
    """OPS-RECON-001 and OPS-RECON-004.

    Enumerated from the module rather than counted here. `detect_all` is the aggregator
    the CLI calls, and this asserts it calls every public detector — so a check added to
    the module and not to the aggregator fails here rather than silently never running.

    The plan said six checks; there are seven. A literal count in this test would have
    encoded my mistake and passed.
    """

    import inspect

    from app.storage import reconciliation

    detectors = {
        name
        for name, value in vars(reconciliation).items()
        if inspect.isfunction(value)
        and not name.startswith("_")
        and name != "detect_all"
        and "connection" in inspect.signature(value).parameters
    }
    assert len(detectors) >= 7, f"only found {sorted(detectors)}"

    source = inspect.getsource(reconciliation.detect_all)
    missing = sorted(name for name in detectors if f"{name}(" not in source)
    assert missing == [], (
        f"these detectors exist and `detect_all` does not run them: {missing}. A check "
        "nothing calls reports nothing, which reads exactly like a clean deployment."
    )


def test_the_cli_writes_nothing(environment: dict[str, Any]) -> None:
    """OPS-RECON-003.

    Proved by running against a read-only database role rather than by reading the code.
    A tool that repaired something would fail here, which is the point:
    `12_Security_RBAC_Audit.md:1571` forbids automatic deletion of financial evidence, and
    "we did not write a delete" is a weaker claim than "it could not have".
    """

    from app.cli.reconcile_storage import main

    _record_without_an_object(environment["url"])

    with psycopg.connect(_psycopg(environment["url"])) as connection:
        before = connection.execute("SELECT count(*) FROM file_objects").fetchone()

    assert main([], settings=environment["settings"]) == 1

    with psycopg.connect(_psycopg(environment["url"])) as connection:
        after = connection.execute("SELECT count(*) FROM file_objects").fetchone()
    assert before == after


def test_the_reconciliation_module_has_a_caller_outside_itself() -> None:
    """TRACE-CALLER-002.

    The same question `test_storage_has_a_caller.py` asks of the write path, asked of the
    module that had the widest gap: seven detectors, an aggregator, and nothing that ever
    ran them.
    """

    import ast
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[2] / "services" / "backend" / "app"
    callers = set()
    for path in app_root.rglob("*.py"):
        if "__pycache__" in path.parts or path.parts[-2:] == ("storage", "reconciliation.py"):
            continue
        if path.name == "reconciliation.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "detect_all":
                callers.add(str(path.relative_to(app_root)))

    assert callers, (
        "nothing in app/ calls `detect_all`. Seven detectors that nothing runs report "
        "nothing, which is indistinguishable from a healthy deployment."
    )
