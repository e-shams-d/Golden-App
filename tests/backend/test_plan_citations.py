"""Every `path:line` citation in a handoff plan must resolve to a real line.

The plans carry the reasoning behind decisions that are already enforced in migrations,
and they cite `path:line` for each claim so a reviewer can check it. Nothing gated those
citations: `infra/scripts/validate_repository.py` validates the *catalogues'* source
references, not a plan's, so a plan could cite a file that no longer exists or a line
past the end of one and read as authoritative.

That is not hypothetical. M2 slice 10A went through the M2 plan by hand and found four
stale claims, one of which cited a document that did not contain the flag it named.

**What this proves, and what it does not.** It proves every file-qualified citation names
a file in the repository and a line inside it. It does **not** prove the cited line says
what the surrounding sentence claims — a citation moved from line 411 to line 1871 by an
edit still resolves. Catching that needs the quoted text checked against the range, which
is a different and larger gate. Stating the limit here because a gate whose reach is
assumed to be wider than it is, is worse than no gate: it converts an unchecked claim into
a apparently-checked one.

What it does catch is the drift that arrives on its own: the Implementation Docs are
revised, a section shortens, and a line number that was right becomes a number past the
end of the file. No human notices until someone follows the citation.

Covers: TRACE-CITE-001.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HANDOFF = REPOSITORY_ROOT / "docs" / "handoff"

# Where a cited path may live. Explicit rather than a repository walk, because a walk
# descends into `node_modules` and turns a fast check into a slow one.
SEARCH_ROOTS = ("", "Implementation Docs", "docs", "services/backend")

# Directories a citation never points into, pruned from the filename index.
PRUNED = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "dist",
        "build",
        # Runtime data the compose stack writes. Gitignored, and owned by container users
        # rather than by the developer — `.gitignore` says exactly that in its own comment.
        # No citation can name a file in here, and walking it does not merely waste time:
        # the storage directory is created 0700 by uid 10001, so `iterdir` raises
        # PermissionError and this module errors during collection, taking the whole
        # backend suite with it.
        #
        # It never surfaced while the working copy lived on a Windows drive, where
        # permissions are permissive enough for the walk to succeed. It appeared the first
        # time the repository sat on ext4 with the stack running.
        ".local",
    }
)

# A citation that names its own file: `path/to/file.md:123` or `...:123-456`, with or
# without surrounding backticks. Bare `:123` citations — which mean "the file named in
# the previous sentence" — are deliberately not matched: resolving them needs prose
# context, and guessing wrong would report failures that are not real.
#
# The basename admits dots. Excluding them read `compose.local.yml` as `local.yml`, which
# resolves to nothing and reported a citation that was correct — a gate whose first output
# is a false positive gets an exception added to it rather than being fixed.
CITATION = re.compile(
    r"`?((?:[A-Za-z0-9_./ -]+/)?[A-Za-z0-9_.-]+\.(?:md|py|yaml|yml|json|ts|tsx|conf|sh|ps1|sql))"
    r"`?:(\d+)(?:-(\d+))?"
)


def plans() -> list[Path]:
    return sorted(HANDOFF.glob("M*_IMPLEMENTATION_PLAN.md"))


def _index() -> dict[str, list[Path]]:
    """Map basename to candidate paths, pruning directories no citation names."""

    found: dict[str, list[Path]] = {}
    stack = [REPOSITORY_ROOT]
    while stack:
        directory = stack.pop()
        for entry in directory.iterdir():
            if entry.name in PRUNED:
                continue
            if entry.is_dir():
                stack.append(entry)
            else:
                found.setdefault(entry.name, []).append(entry)
    return found


INDEX = _index()
_LINE_COUNTS: dict[Path, int] = {}


def resolve(name: str) -> Path | None:
    for root in SEARCH_ROOTS:
        candidate = REPOSITORY_ROOT / root / name if root else REPOSITORY_ROOT / name
        if candidate.is_file():
            return candidate

    candidates = INDEX.get(Path(name).name, [])
    if len(candidates) == 1:
        return candidates[0]
    wanted = name.replace("\\", "/")
    for candidate in candidates:
        if str(candidate).replace("\\", "/").endswith(wanted):
            return candidate
    return None


def line_count(path: Path) -> int:
    if path not in _LINE_COUNTS:
        _LINE_COUNTS[path] = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return _LINE_COUNTS[path]


def citations(plan: Path) -> list[tuple[int, str, str, str]]:
    found = []
    for number, line in enumerate(plan.read_text(encoding="utf-8").splitlines(), start=1):
        for name, start, end in CITATION.findall(line):
            found.append((number, name, start, end))
    return found


def test_there_is_a_plan_to_check() -> None:
    """Guard the guard: an empty glob would make every test below vacuously pass."""

    assert plans(), "no handoff implementation plan was found to check"


@pytest.mark.parametrize("plan", plans(), ids=lambda path: path.name)
def test_every_cited_file_exists(plan: Path) -> None:
    missing = {name for _, name, _, _ in citations(plan) if resolve(name) is None}

    assert not missing, f"{plan.name} cites files that are not in the repository:\n" + "\n".join(
        f"  {name}" for name in sorted(missing)
    )


@pytest.mark.parametrize("plan", plans(), ids=lambda path: path.name)
def test_every_cited_line_is_inside_its_file(plan: Path) -> None:
    problems: list[str] = []
    for number, name, start, end in citations(plan):
        target = resolve(name)
        if target is None:
            continue  # reported by the test above
        total = line_count(target)
        for value in (start, end):
            if value and int(value) > total:
                problems.append(
                    f"{plan.name}:{number} cites {name}:{value}, but that file has {total} lines"
                )
        if end and int(end) < int(start):
            problems.append(f"{plan.name}:{number} cites the reversed range {name}:{start}-{end}")

    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("plan", plans(), ids=lambda path: path.name)
def test_the_plan_actually_cites_its_sources(plan: Path) -> None:
    """A plan with no citations would pass the two tests above without being checked."""

    assert len(citations(plan)) >= 20, (
        f"{plan.name} carries only {len(citations(plan))} file-qualified citations, which is "
        "too few for a milestone plan — either the plan stopped citing its authorities or "
        "the citation pattern no longer matches how it writes them"
    )
