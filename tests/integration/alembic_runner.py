"""Invoke Alembic the way the migrate container does.

A module of its own rather than a conftest helper: pytest puts every test
directory on sys.path unpackaged, so `conftest` is not a unique importable name
once there is more than one test directory.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"


def run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run an Alembic command against `database_url` from the backend project root.

    Settings resolve `env_file` against the working directory, so a repository-root
    .env is invisible from services/backend. Everything required is passed as real
    environment variables instead, which is how the container and CI supply them.
    """

    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
        # Settings requires this to exist; no migration writes to it. Derived from
        # the platform temporary directory so the suite runs on Windows as well as
        # on the Linux runner.
        "LOCAL_STORAGE_ROOT": os.environ.get(
            "LOCAL_STORAGE_ROOT", str(Path(tempfile.gettempdir()) / "itest-storage")
        ),
        "RELEASE_COMMIT": os.environ.get("RELEASE_COMMIT", "0" * 40),
    }
    Path(environment["LOCAL_STORAGE_ROOT"]).mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
