"""Replay the real `infra/postgres/bootstrap/*.sql` against a test database.

The point is that tests measure the file the stack actually runs, not a
restatement of it. `test_audit_append_only_grants.py` currently reproduces the
default-privilege rule by hand; that proves the migration revokes *a* grant, but
it cannot notice if the bootstrap's rule changes underneath it.

`020-runtime-roles.sql` says so itself: "A disposable test database that has not
replayed this file has an empty pg_default_acl and makes SEC-ROLE-006 pass
vacuously. Replay it; do not skip it."

The files are psql scripts, and psycopg cannot execute psql meta-commands. Rather
than depend on a `psql` binary — which is not guaranteed on a CI runner image,
and a gate that fails for a missing client fails for the wrong reason — this
interprets the two constructs the files use:

* `\\set name value` — assign a variable
* `\\gexec` — run the preceding SELECT and execute each returned cell as SQL

`:'name'` and `:"name"` interpolation is handled by psycopg parameters and
`quote_ident`, not by string formatting, so a role name cannot inject SQL.

If either file grows a construct this does not implement, `unsupported_commands`
raises rather than skipping it silently — the failure mode that would otherwise
put the tests back to measuring nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql


@dataclass(frozen=True)
class RuntimeIdentities:
    """Connection strings for the three roles, plus the owner that provisioned them.

    Lives here rather than in conftest because pytest puts every test directory on
    sys.path unpackaged, so `conftest` is not a unique importable name once there
    is more than one test directory — `import conftest` from tests/integration
    resolves to whichever the search finds first.
    """

    owner_url: str
    migrator_url: str
    app_url: str
    worker_url: str
    migrator_role: str
    app_role: str
    worker_role: str

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_DIR = REPOSITORY_ROOT / "infra" / "postgres" / "bootstrap"

# Meta-commands this replayer implements. Anything else must fail loudly.
SUPPORTED_META = ("\\set", "\\gexec")

_META = re.compile(r"^\s*\\(\w+)")
_SET = re.compile(r"^\s*\\set\s+(\S+)\s+(.*?)\s*$")
_LITERAL = re.compile(r":'(\w+)'")
_IDENT = re.compile(r':"(\w+)"')


def unsupported_commands(text: str) -> list[str]:
    """Every psql meta-command in `text` that this replayer does not implement."""

    found: list[str] = []
    for line in text.splitlines():
        match = _META.match(line)
        if match and f"\\{match.group(1)}" not in SUPPORTED_META:
            found.append(line.strip())
    return found


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))


def _render(statement: str, variables: dict[str, str]) -> sql.Composed:
    """Build a Composed statement, quoting identifiers and literals properly.

    String-formatting the values in would make a role name an injection point.
    `sql.Identifier` and `sql.Literal` are what psql's `:"x"` and `:'x'` mean.
    """

    parts: list[sql.Composable] = []
    position = 0
    pattern = re.compile(r":'(\w+)'|:\"(\w+)\"")
    for match in pattern.finditer(statement):
        parts.append(sql.SQL(statement[position : match.start()]))  # type: ignore[arg-type]
        literal_name, ident_name = match.group(1), match.group(2)
        if literal_name is not None:
            parts.append(sql.Literal(variables[literal_name]))
        else:
            parts.append(sql.Identifier(variables[ident_name]))
        position = match.end()
    parts.append(sql.SQL(statement[position:]))  # type: ignore[arg-type]
    return sql.Composed(parts)


def _statements(text: str) -> list[str]:
    """Split on semicolons, with every meta-command its own pseudo-statement.

    Meta-commands are not terminated by a semicolon, so a naive split leaves
    `\\set ON_ERROR_STOP 1` glued to the SQL that follows and the server is asked
    to parse a backslash.
    """

    out: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if "".join(buffer).strip():
            out.append("\n".join(buffer).strip())
        buffer = []

    for line in text.splitlines():
        if line.lstrip().startswith("\\"):
            flush()
            out.append(line.strip())
            continue
        buffer.append(line)
        if line.rstrip().endswith(";"):
            flush()
    flush()
    return [item for item in out if item and item != ";"]


def replay(connection: psycopg.Connection, path: Path, **variables: str) -> None:
    """Execute one bootstrap file against an open, autocommit connection."""

    text = path.read_text(encoding="utf-8")

    unsupported = unsupported_commands(text)
    assert not unsupported, (
        f"{path.name} uses psql meta-commands this replayer does not implement: "
        f"{unsupported}. Implement them rather than skipping the file — a skipped "
        "replay makes the privilege tests pass against a database nobody provisioned."
    )

    resolved = dict(variables)
    pending: sql.Composed | None = None

    for statement in _statements(_strip_comments(text)):
        set_match = _SET.match(statement)
        if set_match:
            # \set ON_ERROR_STOP 1 has no analogue here: psycopg raises on the
            # first error already, which is the behaviour that flag asks for.
            resolved.setdefault(set_match.group(1), set_match.group(2))
            continue

        if statement == "\\gexec":
            assert pending is not None, "\\gexec with no preceding statement"
            for row in connection.execute(pending).fetchall():
                for cell in row:
                    if cell:
                        connection.execute(sql.SQL(cell))  # type: ignore[arg-type]
            pending = None
            continue

        rendered = _render(statement, resolved)
        if statement.lstrip().upper().startswith("SELECT"):
            # Held back: a bare SELECT here exists to feed the \gexec that follows.
            pending = rendered
            continue
        connection.execute(rendered)
        pending = None


def replay_all(connection: psycopg.Connection, **variables: str) -> list[str]:
    """Replay every bootstrap file in name order, as the stack does."""

    replayed: list[str] = []
    for path in sorted(BOOTSTRAP_DIR.glob("*.sql")):
        replay(connection, path, **variables)
        replayed.append(path.name)
    assert replayed, f"no bootstrap files found in {BOOTSTRAP_DIR}"
    return replayed
