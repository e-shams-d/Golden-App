"""The runbooks name things that exist. §20.4: "runbook testing".

M12 slice 4.

**A runbook is followed under pressure, by somebody who has no time to debug it.** A command whose
flag was renamed, a query citing a column that moved, an environment variable nothing reads any
more — each of those turns a recovery into a second incident, and none of them is visible to a
reader who was not looking for it.

## What this gate can and cannot claim

It **cannot** claim the procedures work. Every one of them needs a running server with a certificate
and a domain, which is M13's to provide, and the runbooks say so in their own words rather than
implying otherwise.

It **can** claim they have not rotted:

- every script a runbook tells an operator to run exists, and accepts the flags it is told to pass;
- every repository path a runbook cites is real;
- every database column a runbook's queries name exists in the models;
- every environment variable `secret-rotation.md` names is one `.env.example` declares.

The column check is not hypothetical. While writing slice 2's manifest, `entry_hash` turned out to
be `event_hash` and `version_number` turned out to be `publication_version` — two renames that a
query in a runbook would have carried until somebody ran it at 3am.

## The four the milestone requires

`15_Agent_Implementation_Plan.md:2110` names them: deployment, rollback/forward-fix, incident and
restore. `secret-rotation.md` is the fifth and is OPS-001's answer written where it is used.

Covers: OPS-RUNBOOK-001.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNBOOKS = REPOSITORY_ROOT / "infra" / "runbooks"

# §20.4 and `:2110` name four; the fifth is the owner's OPS-001 decision. Listed rather than
# globbed: a directory that lost `restore.md` would otherwise pass with four files in it.
REQUIRED = {
    "deployment.md",
    "rollback.md",
    "incident.md",
    "restore.md",
    "secret-rotation.md",
}

# Words that appear in these statements and are not column names. **Listed rather than inferred**:
# a check that skipped every word it did not recognise would skip a renamed column too, which is
# precisely the failure this file exists to catch.
_SQL_WORDS = {
    "select", "from", "join", "where", "group", "order", "limit", "desc", "asc",
    "count", "distinct", "interval", "hours", "null", "now", "and", "not", "is",
    "by", "on",
}


def runbook_text() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in RUNBOOKS.glob("*.md")}


def _sql_statements(text: str) -> list[str]:
    """Every `SELECT ... ;` inside a fenced code block, and none of the prose between them."""

    statements: list[str] = []
    for block in re.findall(r"```[a-z]*\n(.*?)```", text, re.S):
        statements.extend(re.findall(r"(SELECT\s.*?;)", block, re.S | re.I))
    return statements


def test_every_required_runbook_exists() -> None:
    """The four §20.5 names, plus OPS-001's."""

    present = set(runbook_text())

    assert present >= REQUIRED, f"missing runbooks: {sorted(REQUIRED - present)}"


def test_every_script_a_runbook_names_exists() -> None:
    """A path that moved makes the instruction unfollowable at the moment it is needed."""

    missing: list[str] = []
    for name, text in runbook_text().items():
        for script in re.findall(r"(infra/scripts/[\w.-]+\.(?:sh|py))", text):
            if not (REPOSITORY_ROOT / script).exists():
                missing.append(f"{name} -> {script}")

    assert missing == [], f"runbooks name scripts that do not exist: {missing}"


def test_every_flag_a_runbook_passes_is_one_the_script_accepts() -> None:
    """**The check that matters most, and the one a reader cannot perform.**

    `backup.sh` took `--container/--database/--user` until CI found that a container name is an
    environment fact; it takes `--database-url` now. A runbook written against the old interface
    would have looked perfectly reasonable and failed on the first argument.
    """

    scripts = {
        path.name: path.read_text(encoding="utf-8")
        for path in (REPOSITORY_ROOT / "infra" / "scripts").glob("*.sh")
    }

    wrong: list[str] = []
    for name, text in runbook_text().items():
        # Each invocation: the script, then every `--flag` up to the next blank line.
        for block in re.findall(r"(infra/scripts/([\w.-]+\.sh)[^\n]*(?:\n\s+[^\n]+)*)", text):
            invocation, script = block
            source = scripts.get(script)
            if source is None:
                continue
            for flag in set(re.findall(r"(--[a-z][a-z-]+)", invocation)):
                # The script's own argument parser is the authority on what it accepts.
                if f"{flag})" not in source:
                    wrong.append(f"{name}: {script} is passed {flag}, which it does not accept")

    assert wrong == [], "runbooks pass flags that do not exist:\n" + "\n".join(wrong)


def test_every_database_column_a_runbook_queries_exists() -> None:
    """A renamed column turns a diagnostic query into a syntax error at the worst moment.

    Checked against the ORM metadata rather than a live database, so this runs in the fast suite —
    and the models are what the migrations produce.
    """

    import app.db.models  # noqa: F401  - importing registers every table on the metadata
    from app.db.base import Base

    columns: dict[str, set[str]] = {
        table: {column.name for column in Base.metadata.tables[table].columns}
        for table in Base.metadata.tables
    }

    wrong: list[str] = []
    for name, text in runbook_text().items():
        # **Only inside fenced code blocks.** A pattern run over the whole document matched from a
        # `SELECT` in one block, through the prose between, to a semicolon in the next — and then
        # reported that "money", "move" and "should" are not columns. A check whose first output is
        # nonsense gets an exception added to it rather than being fixed.
        for statement in _sql_statements(text):
            aliases = {
                alias: table
                for table, alias in re.findall(
                    r"(?:FROM|JOIN)\s+(\w+)\s+(?!ON\b|WHERE\b|GROUP\b|ORDER\b)(\w+)",
                    statement,
                    re.I,
                )
            }
            # `IS DISTINCT FROM b.event_hash` contains the word FROM, so a bare `FROM (\w+)` reads
            # `b` as a table. Anything already bound as an alias is one.
            tables = {
                t.lower()
                for t in re.findall(r"(?:FROM|JOIN)\s+(\w+)", statement, re.I)
                if t not in aliases
            }

            for table in sorted(tables):
                if table not in columns:
                    wrong.append(f"{name}: queries table {table!r}, which does not exist")

            # **Read over the whole statement, not the SELECT list.** A negative control that
            # renamed a column inside a `WHERE` clause was NOT CAUGHT by the first version of this
            # check, which only looked between SELECT and FROM — and `incident.md`'s audit-chain
            # query does all of its real work in `WHERE`.
            for alias, column in re.findall(r"\b(\w+)\.(\w+)\b", statement):
                table = aliases.get(alias, alias).lower()
                if table in columns and column not in columns[table]:
                    wrong.append(f"{name}: {table}.{column} does not exist")

            # Unqualified names, against the tables this statement names.
            known = {column for table in tables for column in columns.get(table, set())}
            for word in re.findall(r"\b([a-z][a-z0-9_]{3,})\b", statement):
                if word in _SQL_WORDS or word in known or word in tables or word in aliases:
                    continue
                wrong.append(f"{name}: {word!r} is not a column of {sorted(tables)}")

    assert wrong == [], "runbooks query columns that do not exist:\n" + "\n".join(wrong)


def test_every_secret_the_rotation_runbook_names_is_declared() -> None:
    """A rotation procedure for a setting nothing reads is a procedure with no effect.

    Worse than useless: somebody rotates it, sees no failure, and concludes the rotation worked.
    """

    declared = set(
        re.findall(
            r"^([A-Z][A-Z0-9_]*)=",
            (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )
    assert declared, ".env.example declares nothing; this check would pass vacuously"

    text = runbook_text()["secret-rotation.md"]
    # Backticked capitals are how this file names a setting.
    named = set(re.findall(r"`([A-Z][A-Z0-9_]{4,})`", text))

    unknown = sorted(named - declared)
    assert unknown == [], (
        f"secret-rotation.md names settings .env.example does not declare: {unknown}. Either the "
        "setting was renamed and the runbook rotates nothing, or it is missing from the example."
    )


def test_every_runbook_says_how_it_is_tested() -> None:
    """Including when the answer is "it is not".

    `an-exemption-must-name-its-mechanism`. A runbook with no such section reads as verified by
    whoever reaches for it under pressure, and three of these five are **not** executed by any test
    — which is a fact an operator deserves before they rely on one.
    """

    thin = [
        name
        for name, text in runbook_text().items()
        if "How this runbook is tested" not in text
    ]

    assert thin == [], f"these runbooks do not say how they are tested: {thin}"


def test_the_restore_runbook_names_the_ownership_step() -> None:
    """The step the restore script cannot perform, and the one a recovery fails without.

    `pg_restore --no-owner` leaves every object owned by the connecting role, so the application's
    roles have no rights on their own tables. Slice 2's drill deliberately does not cover it — it
    reads the restored database as the role that restored it — which makes this runbook the only
    place the step is recorded.
    """

    text = runbook_text()["restore.md"]

    assert "020-runtime-roles.sql" in text, (
        "the restore runbook does not say to re-apply the runtime grants, and nothing else does"
    )
    assert "permission denied" in text, (
        "the runbook does not say what the failure looks like, which is how an operator recognises "
        "they skipped the step"
    )
