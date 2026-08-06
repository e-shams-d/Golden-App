"""Nothing in this codebase can delete a record. Asserted structurally.

Slice 7 ships `retention_policies` and `legal_holds` and no executor for either.
That is a deliberate non-delivery, and a non-delivery is the one kind of promise
that decays without anyone noticing: nobody reviews a pull request looking for the
purge job it *added*, because adding one looks like finishing the feature.

ADR-005 is open. Until the governed procedure exists — proposal, review, approval,
legal-hold check, dry-run impact report, backup coordination, activation, then a
separate execution step with its own evidence — a deletion path has no authority to
run under, so the correct amount of deletion machinery is none.

The checks below are structural rather than textual. A grep for "purge" would flag
`recover_stale_leases_task`, which sweeps nothing away — it reports leases whose
holder died — and would miss a purge spelled `tidy_up`. So instead: the columns
that would model a soft delete, the calls that would issue a DELETE, the SQL that
would create a trigger, and the routes that would expose any of it.

The most valuable one is the last. Everything else is reachable only by a
scheduled task or a migration, both of which change in a diff a reviewer reads. A
route is reachable by anyone holding a token.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
import pytest
from app.db.base import Base
from app.workers.celery_app import BEAT_SCHEDULE

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "services" / "backend"
APP_ROOT = BACKEND_ROOT / "app"
MIGRATIONS_ROOT = BACKEND_ROOT / "alembic"

# A soft-delete column applies one meaning of "deleted" to every table that
# carries it. The approved model is a governed, table-specific state — a payment
# request is `cancelled`, an export `superseded`, an evidence link `replaced` —
# because those three mean different things and a shared `deleted_at` says they
# do not.
SOFT_DELETE_COLUMNS = frozenset({"deleted_at", "is_deleted", "deleted", "removed_at", "purged_at"})

# Methods that would let a caller delete an aggregate without naming which table
# and which governed state transition it means.
GENERIC_DELETE_METHODS = frozenset({"delete", "soft_delete", "remove", "purge", "destroy"})

# `GRANT UPDATE, DELETE` is a privilege rather than a deletion and matches none of
# these; `\btruncate\b` does not match the prose "PostgreSQL truncates identifiers"
# or the `[TRUNCATED]` log marker.
FORBIDDEN_SQL = (
    re.compile(r"\bdelete\s+from\b"),
    re.compile(r"\btruncate\b"),
    re.compile(r"\bcreate\s+(or\s+replace\s+)?trigger\b"),
    re.compile(r"\bcreate\s+rule\b"),
)


def python_sources(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def docstrings(module: ast.Module) -> set[int]:
    """The string nodes that are prose, identified by position rather than content.

    `db/base.py` documents that "PostgreSQL would silently truncate at 63 bytes",
    and a scan that read that as SQL would be a test failing on its own
    explanation — the exact failure mode that made
    `test_package_is_relocatable.py` tokenise instead of grep. A docstring is the
    first statement of a module, class or function, which is a structural fact and
    not a guess about wording.
    """

    found: set[int] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def forward_running(node: ast.AST) -> Iterator[ast.AST]:
    """Every node except the bodies of `downgrade()`, pruned rather than filtered.

    A downgrade legitimately removes what its own upgrade added — 20260801_0008's
    removes the seeded role grants — and it is a developer action run by hand
    against a database being rewound, not a path any deployment or request
    reaches. The policy on downgrades is forward-fix, enforced by review of the
    revision itself; what this test is for is code that runs going forward.

    `ast.walk` cannot express this: skipping the function node still visits its
    children, so the prune has to be a recursive descent.
    """

    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name == "downgrade":
            continue
        yield child
        yield from forward_running(child)


def test_no_mapped_table_carries_a_soft_delete_column() -> None:
    """DB-DELETE-001, first half: no table gets one mechanically.

    Checked against `Base.metadata` rather than the source, so a column added by a
    mixin, a base class or a loop is caught the same as one written out.
    """

    offenders = [
        f"{table_name}.{column.name}"
        for table_name, table in sorted(Base.metadata.tables.items())
        for column in table.columns
        if column.name in SOFT_DELETE_COLUMNS
    ]

    assert offenders == [], (
        "soft-delete columns found: "
        + ", ".join(offenders)
        + ". Deletion is modelled as a governed, table-specific state, not as a "
        "flag that means something different on every table."
    )


@pytest.mark.parametrize("method", sorted(GENERIC_DELETE_METHODS))
def test_the_declarative_base_exposes_no_generic_delete(method: str) -> None:
    """DB-DELETE-001, second half.

    A `delete()` on the base is the shortest path from "this row is wrong" to a
    financial record that no longer exists. Inherited by every future table at
    once, which is why the absence is checked here rather than per model.
    """

    assert not hasattr(Base, method), (
        f"Base exposes {method}(), which every mapped model would inherit. A "
        "deletion must name its table and its governed state transition."
    )


def test_no_runtime_module_issues_a_delete() -> None:
    """No `session.delete(...)`, no `sqlalchemy.delete(...)`, anywhere in `app/`.

    AST rather than text, so `ondelete="CASCADE"` on a role-grant foreign key and
    `NamedTemporaryFile(delete=False)` are not confused with a call — both are
    keyword arguments, and neither deletes a record.
    """

    offenders: list[str] = []
    for path in python_sources(APP_ROOT):
        for node in ast.walk(parsed(path)):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.attr
                if isinstance(function, ast.Attribute)
                else function.id
                if isinstance(function, ast.Name)
                else None
            )
            if name in {"delete", "delete_all"}:
                offenders.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}: {name}(...)")

    assert offenders == [], (
        "runtime code issues a delete:\n"
        + "\n".join(offenders)
        + "\nADR-005 is open; no governed procedure authorises this yet."
    )


def test_no_sql_string_deletes_rows_or_installs_a_trigger() -> None:
    """Covers what the AST check cannot: deletion written as raw SQL.

    Migrations are scanned too. A trigger is the worst case of all — it deletes
    without any call site to find, so a reader of the application code would have
    no way to discover it exists.
    """

    offenders: list[str] = []
    for root in (APP_ROOT, MIGRATIONS_ROOT):
        for path in python_sources(root):
            module = parsed(path)
            prose = docstrings(module)
            for node in forward_running(module):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if id(node) in prose:
                    continue
                compact = " ".join(node.value.lower().split())
                for pattern in FORBIDDEN_SQL:
                    if pattern.search(compact):
                        offenders.append(
                            f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}: "
                            f"matches {pattern.pattern}"
                        )

    assert offenders == [], "SQL that removes rows or installs a trigger:\n" + "\n".join(offenders)


def test_the_scheduled_tasks_are_exactly_the_two_recovery_sweeps() -> None:
    """Pinned, so a retention or expiry job cannot arrive as an extra dict entry.

    Both entries here recover from a process death: one re-dispatches an outbox
    row whose after-commit hook was lost, the other reports leases whose holder
    disappeared. Neither removes anything. `idempotency_records.expires_at` has an
    index and nothing that acts on it, and sweeping it would destroy exactly the
    rows that prove no duplicate financial command was accepted.
    """

    assert set(BEAT_SCHEDULE) == {"outbox-dispatch", "stale-lease-sweep"}


def test_no_route_exposes_a_deletion_or_a_retention_action(app_factory) -> None:
    """The one that matters: nothing reachable over HTTP can invoke any of this.

    No DELETE method on any route, and no path naming retention or legal holds —
    the tables exist for review, and review is a read that M2 does not ship
    either.
    """

    app, _runtime, _settings = app_factory()

    # `app.routes` is not uniform: alongside the request routes it holds mounts
    # and the router objects FastAPI keeps for included sub-routers, and neither
    # carries `path` or `methods`. Reading them defensively rather than filtering
    # by type, so a future entry kind cannot quietly drop out of the scan.
    paths = [getattr(route, "path", "") for route in app.routes]

    delete_routes = [
        f"{sorted(methods)} {getattr(route, 'path', route)}"
        for route in app.routes
        if "DELETE" in (methods := getattr(route, "methods", None) or set())
    ]
    assert delete_routes == [], "routes accepting DELETE:\n" + "\n".join(delete_routes)

    governed = [
        path
        for path in paths
        if any(word in path for word in ("retention", "legal-hold", "legal_hold", "purge"))
    ]
    assert governed == [], (
        "routes touching retention or legal holds exist: "
        + ", ".join(governed)
        + ". ADR-005 is open and these tables are structure only."
    )
