"""The application package must not depend on where the repository puts it.

This exists because of a failure the whole test suite missed. `app/audit/registry.py`
resolved the governance catalogue as `Path(__file__).resolve().parents[4] / "docs"`,
which is correct in a source checkout and raises IndexError inside the container,
where the package sits at `/app/app` and has no fourth parent. `docs/` is not
copied into the image either, so even a correct path would have found nothing.

Every unit and integration test passed. The backend then failed to start in the
Docker acceptance stack, and the only symptom was an unhealthy container.

The tests below reproduce the container's shape directly rather than waiting for
a full stack build, so the same mistake fails in seconds instead of minutes.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "services" / "backend"
APP_ROOT = BACKEND_ROOT / "app"


def code_lines(path: Path) -> list[tuple[int, str]]:
    """Executable source only: no comments, no docstrings, no string contents.

    Scanning raw text would flag the prose that documents these very rules — the
    module docstring in `audit/registry.py` quotes the broken expression on
    purpose. Tokenising keeps the guard pointed at code.
    """

    text = path.read_text(encoding="utf-8")
    skip = {tokenize.COMMENT, tokenize.STRING, tokenize.FSTRING_START, tokenize.FSTRING_MIDDLE}
    lines: dict[int, list[str]] = {}
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in skip or token.type == tokenize.NL:
            continue
        lines.setdefault(token.start[0], []).append(token.string)
    return [(number, " ".join(parts)) for number, parts in sorted(lines.items())]


def test_the_app_imports_from_a_container_shaped_location(tmp_path: Path) -> None:
    """Copy the package to a shallow path with no repository above it and import it.

    `/app/app` in the image has exactly three parents. Anything reaching further
    up, or expecting a sibling `docs/` or `tests/`, breaks here.
    """

    target = tmp_path / "app"
    shutil.copytree(APP_ROOT, target, ignore=shutil.ignore_patterns("__pycache__"))

    result = subprocess.run(
        [sys.executable, "-c", "import app.main; print('imported')"],
        cwd=tmp_path,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(tmp_path),
            # Importing app.main must not require configuration; Settings is
            # constructed by the entrypoint, not at import time.
            "SYSTEMROOT": "C:\\Windows",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "the application package cannot be imported outside the repository layout, "
        "so it will crash on start inside the container.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_no_runtime_module_reaches_for_a_repository_document() -> None:
    """Runtime code must not read anything that only exists in a checkout.

    Governance documents, fixtures and test data are not shipped in the image.
    Reading one at import time turns a missing file into a crash on start; reading
    one lazily turns it into a failure the first time a real request needs it.
    Checking those documents is a test's job.
    """

    # String *contents* are skipped by the tokeniser, so a literal path is caught
    # by the parents[] rule below and by the import test above rather than here.
    # What this catches is a module naming those directories in code.
    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        for line_number, line in code_lines(path):
            if "docs" in line.split() or "governance" in line.split():
                offenders.append(f"{path.relative_to(APP_ROOT)}:{line_number}: {line}")

    assert offenders == [], (
        "runtime modules reference repository-only paths; the container does not "
        "have them:\n" + "\n".join(offenders)
    )


def test_no_runtime_module_walks_above_the_package_root() -> None:
    """`parents[N]` beyond the package is a repository-layout assumption.

    The package root is `app/`. Inside the image its absolute path is `/app/app`,
    so `parents[3]` is already `/` and `parents[4]` raises. A module that needs a
    sibling of the repository root is making an assumption the image does not
    honour.
    """

    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        depth_below_app = len(path.relative_to(APP_ROOT).parts) - 1
        for line_number, line in code_lines(path):
            compact = line.replace(" ", "")
            for index in range(depth_below_app + 1, 9):
                if f"parents[{index}]" in compact:
                    offenders.append(
                        f"{path.relative_to(APP_ROOT)}:{line_number} uses parents[{index}], "
                        f"which leaves the package (depth {depth_below_app})"
                    )

    assert offenders == [], "\n".join(offenders)
