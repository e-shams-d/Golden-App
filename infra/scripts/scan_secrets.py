"""Conservative, dependency-free secret scan for files intended for Git transfer.

This catches high-confidence credential formats and accidentally tracked environment
files. It complements, but does not replace, a maintained scanner such as Gitleaks
and an image/registry scan in CI.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

IGNORED_DIRECTORIES = {
    ".agents",
    ".git",
    ".local",
    ".mypy_cache",
    ".next",
    ".pnpm-store",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    ".venv",
    "__pycache__",
    "node_modules",
    "playwright-report",
    "test-results",
}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        ),
    ),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    (
        "GitHub fine-grained token",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,255}\b"),
    ),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,255}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,255}\b")),
    ("Stripe live key", re.compile(r"\bsk_live_[A-Za-z0-9]{16,255}\b")),
    ("Google API key", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
)


def git_visible_files() -> list[Path]:
    """Return tracked and untracked, non-ignored files in deterministic order."""

    try:
        result = subprocess.run(
            [
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return fallback_files()

    relative_paths = [
        Path(raw.decode("utf-8", errors="surrogateescape"))
        for raw in result.stdout.split(b"\0")
        if raw
    ]
    return sorted((ROOT / path for path in relative_paths), key=lambda path: path.as_posix())


def fallback_files() -> list[Path]:
    files: list[Path] = []
    for current, directories, filenames in os.walk(ROOT, followlinks=False):
        directories[:] = sorted(
            name for name in directories if name not in IGNORED_DIRECTORIES
        )
        files.extend(Path(current, name) for name in sorted(filenames))
    return sorted(files, key=lambda path: path.as_posix())


def is_unexpected_environment_file(path: Path) -> bool:
    name = path.name.lower()
    if name == ".env.example":
        return False
    return name == ".env" or name.startswith(".env.")


def main() -> int:
    findings: list[str] = []
    scanned_text_files = 0
    files = git_visible_files()

    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if is_unexpected_environment_file(path):
            findings.append(f"{relative}: environment file must not be transferred by Git")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned_text_files += 1
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match is not None:
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{relative}:{line}: possible {label}")

    if findings:
        print("High-confidence transfer secret scan failed:")
        for finding in sorted(findings):
            print(f"- {finding}")
        return 1

    print(
        "High-confidence transfer secret scan passed: "
        f"{scanned_text_files} text files ({len(files)} Git-visible files)."
    )
    print("A maintained CI scanner and container-image scan are still required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
