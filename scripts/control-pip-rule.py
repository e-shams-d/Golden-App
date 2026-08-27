"""Negative control for the pip-removal rule in validate_repository.py.

Written in Python rather than perl-through-a-shell because the pattern needs to survive two levels of
quoting otherwise, and two attempts at that produced sabotages that never applied — a NOT CAUGHT
that says nothing about the rule.

Two sabotages. The second is the one that matters: a gate reading whole-file text can be satisfied by
the comment that explains the thing it looks for, which has defeated scans in this repository seven
times. This rule was written the same way, so it needs asking.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Derived, not hardcoded. The first version pinned an absolute home directory, which works on
# exactly one machine — the kind of thing that only ever fails for the next person.
ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "infra" / "docker" / "backend.Dockerfile"
VALIDATOR = ROOT / "infra" / "scripts" / "validate_repository.py"
PYTHON = ROOT / "services" / "backend" / ".venv" / "bin" / "python"

original = DOCKERFILE.read_text(encoding="utf-8")

RUN_START = "RUN rm -rf /usr/local/lib/python3.12/site-packages/pip"
COMMENT_START = "# **The runtime image carries no package manager**"


def run_validator() -> tuple[bool, str]:
    finished = subprocess.run(
        [str(PYTHON), str(VALIDATOR)], capture_output=True, text=True, cwd=ROOT
    )
    return finished.returncode == 0, finished.stdout + finished.stderr


def check(label: str, sabotaged: str) -> None:
    assert sabotaged != original, f"sabotage did not apply: {label}"
    DOCKERFILE.write_text(sabotaged, encoding="utf-8", newline="\n")
    try:
        passed, output = run_validator()
        if passed:
            print(f"  NOT CAUGHT  {label}")
        elif "ships pip into the runtime" in output:
            print(f"  CAUGHT   {label:<48} (on: ships pip into the runtime)")
        else:
            print(f"  CAUGHT   {label:<48} *** WRONG MESSAGE ***")
            print("    " + output.strip().splitlines()[-1])
    finally:
        DOCKERFILE.write_text(original, encoding="utf-8", newline="\n")


def without_the_run(text: str) -> str:
    """Drop the RUN block, keeping the comment above it."""

    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith(RUN_START))
    end = start
    while end < len(lines) and lines[end].rstrip("\n").endswith(("\\", "2>/dev/null")):
        end += 1
    return "".join(lines[:start] + lines[end:])


def without_comment_or_run(text: str) -> str:
    """Drop the comment as well, which is the plain regression."""

    lines = without_the_run(text).splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith(COMMENT_START))
    end = start
    while end < len(lines) and lines[end].startswith("#"):
        end += 1
    return "".join(lines[:start] + lines[end:])


print("== control: the pip-removal rule ==")
try:
    check("the removal is deleted with its comment", without_comment_or_run(original))
    check("only the RUN is deleted, the comment stays", without_the_run(original))
finally:
    DOCKERFILE.write_text(original, encoding="utf-8", newline="\n")
    restored = DOCKERFILE.read_text(encoding="utf-8") == original
    print(f"== done (restored: {restored}) ==")
    sys.exit(0 if restored else 1)
