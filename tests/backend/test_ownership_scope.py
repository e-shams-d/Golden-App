"""No query may read trader-owned rows without going through the scope helper.

`SVC-SCOPE-001`. The ownership rule is one line — `WHERE trader_id = ?` — and one
line is exactly the kind of rule that holds until someone adds a listing endpoint
in a hurry. This checks it structurally instead of trusting review.

**What counts as trader-owned** is read from the mapped models rather than
listed here: any table carrying a `trader_id` column. A hand-written list would
be a second copy that stops matching the schema the first time a table is added,
and the failure would be silent in the direction that matters — a new owned table
nobody added to the list is a new table nobody scopes.

The rule is deliberately narrow. It fires on a `select(...)` naming an owned model
inside `services/backend/app`, and is satisfied by that statement passing through
`ownership.scoped(...)` in the same function. It does not try to follow the
statement across function boundaries; a helper that returns an unscoped statement
for someone else to scope is a shape this codebase does not use, and pretending to
check it would claim more than the parse can support.

Covers: SVC-SCOPE-001.
"""

from __future__ import annotations

import ast
from pathlib import Path

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
import pytest
from app.db.base import Base

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPOSITORY_ROOT / "services" / "backend" / "app"

# Functions that must read an owned table with no actor to scope by, each with the
# reason. Keyed by `module::function` so a rename drops the exemption rather than
# carrying it to different code — and `test_every_exemption_still_names_live_code`
# fails on an entry naming a function that no longer exists.
#
# The bar for adding one is narrow: the query must run *before* an ActorContext
# can exist. Anything after authentication has an actor and must scope.
SCOPE_EXEMPT: dict[str, str] = {
    "commands/authenticate.py::_load_identity": (
        "the login lookup by phone number, which runs before any session exists. "
        "There is no actor to scope by yet — establishing one is what this query is "
        "for. It is scoped by the unique login identifier instead, and returns at "
        "most one row."
    ),
    "commands/payment_batch.py::_verify_sources_are_still_current": (
        "M6 slice 3's finalization guard. A batch version deliberately carries rows belonging "
        "to **many** traders — it is one file the centre sends to a bank — and this query "
        "re-reads exactly the requests that version already contains, to check that their "
        "revisions are still current and their statuses still eligible before a manager is "
        "shown the version. Scoping it to one trader would make the guard read a subset of the "
        "rows it is guarding, which is the failure mode inverted: it would silently pass a "
        "version whose *other* traders' requests had moved.\n"
        "\n"
        "It is not unbounded. The id set comes from `payment_batch_items` for one version, so "
        "the query returns only rows already in the batch, and the route above it is guarded by "
        "`payment_batch_version.finalize`, which `permission_catalog.yaml:472` gives to no "
        "trader role. `tests/integration/test_batch_finalization.py` asserts that no trader can "
        "reach the route at all, which is the ownership question answered where it belongs."
    ),
}


def owned_models() -> set[str]:
    """Every mapped class whose table carries `trader_id`.

    Derived from the metadata so a table added in M5 is covered the moment it
    exists, without anyone remembering to update this file.
    """

    owned = set()
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if table is not None and "trader_id" in table.columns:
            owned.add(mapper.class_.__name__)
    return owned


def unscoped_selects(path: Path, owned: set[str]) -> list[str]:
    """`select(OwnedModel)` calls in a function that never calls `scoped`."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    findings: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        selects: list[tuple[int, str]] = []
        scopes = False

        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            name = getattr(inner.func, "id", None) or getattr(inner.func, "attr", None)
            if name == "scoped":
                scopes = True
            if name != "select":
                continue
            for argument in inner.args:
                target = getattr(argument, "id", None) or getattr(argument, "attr", None)
                if target in owned:
                    selects.append((inner.lineno, target))

        if not selects or scopes:
            continue

        try:
            module = path.relative_to(APP_ROOT).as_posix()
        except ValueError:
            module = path.name  # a planted file in tmp_path, used by the control below
        if f"{module}::{node.name}" in SCOPE_EXEMPT:
            continue

        for line, target in selects:
            findings.append(
                f"{module}:{line} {node.name}() selects {target} without ownership scoping"
            )
    return findings


def test_there_are_owned_models_to_check() -> None:
    """Guard the guard: an empty owned set makes every assertion below vacuous."""

    owned = owned_models()

    assert "TraderUser" in owned, (
        "trader_users carries trader_id and must be recognised as owned; if this "
        "fails the metadata reader is broken and the gate below checks nothing"
    )


def test_every_exemption_still_names_live_code() -> None:
    """A stale exemption is worse than a missing one.

    It goes on reading like a considered decision while the renamed function it
    once described drops out of the gate entirely — the same failure the route
    allowlist in `test_permission_guards.py` guards against.
    """

    stale = []
    for key in SCOPE_EXEMPT:
        module, _, function = key.partition("::")
        path = APP_ROOT / module
        if not path.is_file() or f"def {function}(" not in path.read_text(encoding="utf-8"):
            stale.append(key)

    assert stale == [], f"exemptions naming code that no longer exists: {stale}"


def test_no_owned_model_is_selected_without_scoping() -> None:
    owned = owned_models()
    findings = [
        finding
        for path in sorted(APP_ROOT.rglob("*.py"))
        for finding in unscoped_selects(path, owned)
    ]

    assert findings == [], (
        "these queries read trader-owned rows without passing through "
        "app.security.ownership.scoped(), so nothing restricts them to the "
        "caller's own trader:\n" + "\n".join(f"  {entry}" for entry in findings)
    )


def test_the_reader_detects_a_planted_violation(tmp_path: Path) -> None:
    """Guard the guard, the other way.

    A parser that matched nothing would pass the gate above for every file. This
    plants the exact shape the rule forbids and requires it to be seen — and then
    plants the scoped version and requires it not to be.
    """

    violation = tmp_path / "violation.py"
    violation.write_text(
        "from sqlalchemy import select\n"
        "from app.db.models.identity import TraderUser\n\n"
        "def leaky(session):\n"
        "    return session.scalars(select(TraderUser)).all()\n",
        encoding="utf-8",
    )
    compliant = tmp_path / "compliant.py"
    compliant.write_text(
        "from sqlalchemy import select\n"
        "from app.db.models.identity import TraderUser\n"
        "from app.security.ownership import scoped\n\n"
        "def safe(session, actor):\n"
        "    statement = scoped(select(TraderUser), TraderUser.trader_id, actor)\n"
        "    return session.scalars(statement).all()\n",
        encoding="utf-8",
    )

    owned = {"TraderUser"}

    assert unscoped_selects(violation, owned), "the reader missed a plain unscoped select"
    assert unscoped_selects(compliant, owned) == [], (
        "the reader flagged a correctly scoped query, so the rule would be "
        "suppressed rather than followed"
    )


class TestScopeHelper:
    def test_an_internal_actor_cannot_scope(self) -> None:
        """Doc 12:316. An admin is not an owner, and asking is a bug not a denial."""

        import uuid

        from app.db.models.identity import TraderUser
        from app.security.actor import ActorContext, ActorType, Audience
        from app.security.ownership import OwnershipScopeError, scoped
        from sqlalchemy import select

        admin = ActorContext(
            actor_type=ActorType.ADMIN_USER,
            actor_id=uuid.uuid4(),
            audience=Audience.ADMIN,
            session_id=uuid.uuid4(),
            security_stamp_version=1,
        )

        with pytest.raises(OwnershipScopeError, match="support workflow"):
            scoped(select(TraderUser), TraderUser.trader_id, admin)

    def test_a_trader_scope_narrows_the_statement(self) -> None:
        import uuid

        from app.db.models.identity import TraderUser
        from app.security.actor import ActorContext, ActorType, Audience
        from app.security.ownership import scoped
        from sqlalchemy import select

        trader_id = uuid.uuid4()
        trader = ActorContext(
            actor_type=ActorType.TRADER_USER,
            actor_id=uuid.uuid4(),
            audience=Audience.TRADER,
            session_id=uuid.uuid4(),
            security_stamp_version=1,
            trader_id=trader_id,
        )

        plain = str(select(TraderUser))
        narrowed = str(scoped(select(TraderUser), TraderUser.trader_id, trader))

        assert "WHERE" not in plain
        assert "trader_users.trader_id =" in narrowed

    def test_not_mine_and_not_existing_are_the_same_refusal(self) -> None:
        """SEC-IDOR-005. A 404/403 split over guessable ids is an existence oracle."""

        import uuid

        from app.core.errors import NotFoundError
        from app.security.actor import ActorContext, ActorType, Audience
        from app.security.ownership import require_owned

        trader = ActorContext(
            actor_type=ActorType.TRADER_USER,
            actor_id=uuid.uuid4(),
            audience=Audience.TRADER,
            session_id=uuid.uuid4(),
            security_stamp_version=1,
            trader_id=uuid.uuid4(),
        )

        with pytest.raises(NotFoundError) as missing:
            require_owned(None, None, trader)

        with pytest.raises(NotFoundError) as not_mine:
            require_owned(object(), uuid.uuid4(), trader)

        assert missing.value.code == not_mine.value.code
        assert missing.value.status_code == not_mine.value.status_code
        assert missing.value.message == not_mine.value.message
