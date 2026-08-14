"""TRACE-PLAN-001: a governance record's evidence must name something that exists.

**This obligation had no definition.** `TRACE-PLAN-001` appears exactly twice in the
repository: once in the M3 plan's line deferring it to slice 1B, and once in the pending
ledger recording that deferral. Nothing anywhere said what it required. It was carried for
two milestones as a name with a milestone attached and no content — which is its own small
instance of the problem it is now defined to catch.

So slice 1B defines it, from the failure that slice found rather than from the name.

## What it requires

`CONFLICT_REGISTER.md` records an approved resolution for each conflict, and many of those
resolutions name the thing that enforces them: *"`tests/integration/test_constraint_names.py`
asserts the doc-04 names exist verbatim."* That sentence is a claim about the codebase, and
until this file nothing checked it.

It was false. DOC-CONFLICT-042 was approved on 2026-08-06 with the rule that an index
document 04 names keeps that name verbatim, and cited that test as its evidence. The test
compares the database against what the **models** compile to; it has never read document
04. Six indexes drifted from their specified names under a rule a governance record said
was enforced — found by `tests/integration/test_schema_matches_the_specification.py`, which
is the gate that actually reads the specification.

The damage of a wrong evidence citation is specific: a reviewer who checks whether a rule is
enforced finds a named test, sees it green, and stops. The citation converts an unchecked
rule into an apparently-checked one, which is worse than no citation at all — the second
invites the check that the first prevents.

## What this proves, and what it does not

It proves every file a register row names as evidence exists, and that a row claiming a
*test* as evidence names a file the suite actually collects.

It does **not** prove the test asserts what the row says it asserts. That needs a human
reading both, and no gate can stand in for it. The limit is stated because the whole point
of this obligation is that an evidence claim nobody verified is worse than an absent one,
and a gate whose reach is assumed to be wider than it is would be exactly that mistake
made again, one level up.

Covers: TRACE-PLAN-001.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REGISTER = REPOSITORY_ROOT / "docs" / "governance" / "CONFLICT_REGISTER.md"

# A path inside backticks: `tests/integration/test_constraint_names.py`,
# `app/db/base.py:23-29`. The line suffix is stripped — `test_plan_citations.py` already
# checks that a cited line exists, and duplicating it here would be a second thing to keep
# working for no additional claim.
_CITED_PATH = re.compile(
    r"`([A-Za-z0-9_./-]+\.(?:py|ts|tsx|md|yaml|yml|json|sql|sh))(?::\d+(?:-\d+)?)?`"
)

# Where a cited path may live, mirroring `test_plan_citations.py`'s roots so a register row
# and a plan citation resolve the same way.
SEARCH_ROOTS = ("", "Implementation Docs", "docs", "services/backend", "tests")

# Directories no citation points into. Same list and same reason as `test_plan_citations.py`:
# `.local` is created 0700 by a container user, so walking it raises PermissionError during
# collection and takes the whole suite with it.
PRUNED = frozenset(
    {"node_modules", ".git", "__pycache__", ".venv", "dist", "build", ".next", ".local"}
)


def _basename_index() -> dict[str, list[Path]]:
    """Map basename to candidate paths.

    Needed because the register cites the implementation documents by bare filename —
    `12_Security_RBAC_Audit.md` — and they live two directories deep under
    `Implementation Docs/`. The first version of this gate checked a fixed list of roots and
    reported five real files as missing, which would have made its first output a false
    positive: the failure mode where somebody adds an exception instead of fixing the check.
    """

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


_INDEX = _basename_index()


def cited_paths() -> dict[str, list[int]]:
    """Every file path the register cites, mapped to the lines citing it."""

    found: dict[str, list[int]] = {}
    for number, line in enumerate(REGISTER.read_text(encoding="utf-8").splitlines(), start=1):
        for path in _CITED_PATH.findall(line):
            found.setdefault(path, []).append(number)
    return found


def resolve(name: str) -> Path | None:
    for root in SEARCH_ROOTS:
        candidate = REPOSITORY_ROOT / root / name if root else REPOSITORY_ROOT / name
        if candidate.is_file():
            return candidate

    candidates = _INDEX.get(Path(name).name, [])
    if len(candidates) == 1:
        return candidates[0]
    wanted = name.replace("\\", "/")
    for candidate in candidates:
        if str(candidate).replace("\\", "/").endswith(wanted):
            return candidate
    return None


def test_the_register_still_cites_its_evidence() -> None:
    """Guard the guard: a register that cited nothing would pass every check below.

    The floor is derived from what the file contains rather than from a number somebody
    chose — a pattern that stopped matching yields an empty mapping, and an empty mapping
    makes "every cited file exists" trivially true.
    """

    cited = cited_paths()

    assert len(cited) >= 15, (
        f"only {len(cited)} file citations were parsed out of {REGISTER.name}; either the "
        "register stopped citing its sources or the pattern no longer matches how it "
        "writes them, and every assertion below is now about nothing"
    )


@pytest.mark.parametrize("path", sorted(cited_paths()))
def test_every_file_the_register_names_exists(path: str) -> None:
    """A resolution whose evidence names a missing file is a resolution nobody can check."""

    assert resolve(path) is not None, (
        f"CONFLICT_REGISTER.md cites {path} at line(s) {cited_paths()[path]}, and no such "
        "file is in the repository. A governance record whose evidence cannot be opened "
        "reads as verified and is not."
    )


def test_every_test_the_register_claims_as_evidence_is_collected() -> None:
    """A row naming a test file must name one the suite actually runs.

    Weaker than "the test asserts what the row says", which needs a human — and that limit
    is in the module docstring rather than hidden here. What it does catch is a row citing a
    file that was renamed, moved out of the suite, or never written.
    """

    missing: list[str] = []
    for path in sorted(cited_paths()):
        if "test_" not in Path(path).name:
            continue
        resolved = resolve(path)
        if resolved is None:
            continue  # reported by the parametrised test above
        if "tests" not in resolved.parts:
            missing.append(f"{path} is cited as evidence and is not under tests/")

    assert missing == [], "\n".join(missing)


def test_doc_conflict_042_no_longer_claims_evidence_it_does_not_have() -> None:
    """The specific falsehood this obligation was defined from.

    Pinned by name rather than left to the general check, because the general check cannot
    see it: `test_constraint_names.py` exists and is collected, so every structural
    assertion above passes over a row that was still wrong. Only a reader comparing the two
    could find it, and this test is that reading, written down so it does not have to
    happen twice.
    """

    text = REGISTER.read_text(encoding="utf-8")
    row = next((line for line in text.splitlines() if "DOC-CONFLICT-042" in line), "")

    assert row, "DOC-CONFLICT-042 has left the register; this pin needs re-deriving"
    assert "test_schema_matches_the_specification.py" in row, (
        "DOC-CONFLICT-042's evidence must name the gate that reads document 04. It "
        "previously named test_constraint_names.py, which compares the database to the "
        "models and has never opened the specification — so the rule it claimed to enforce "
        "went unenforced and six indexes drifted from their specified names."
    )
