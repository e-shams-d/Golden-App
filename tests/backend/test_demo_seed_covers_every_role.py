"""Every role a person can hold has somebody to sign in as in the demonstration. A-3.

The acceptance pass found no seeded account for the warehouse operator, and `gold_sale.dispatch`
is that role's alone — so the gold-dispatch milestone could not be shown with the identities the
demo seed prints. The roles come from the RBAC seed migration, not from this file, so a role added
there without a demonstration account fails here.

Two roles are covered by something other than `COLLEAGUES`, and each exemption names its
mechanism and is checked rather than stated:

- `business_admin` is the bootstrap account. `create_first_admin` accepts only a role holding
  `user.create`, the seed refuses to run without that account and attributes every decision to
  it — and the test below confirms `business_admin` is the only role holding `user.create`.
- `trader_owner` describes the trader side, which holds no grants at all: `ActorContext` refuses
  them, and a trader is authorised by identity and ownership. Each seeded business's primary
  contact is the account that signs in as that side.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    REPOSITORY_ROOT
    / "services"
    / "backend"
    / "alembic"
    / "versions"
    / "20260801_0008_seed_rbac_catalogue.py"
)

COVERED_ELSEWHERE = {
    "business_admin": "the bootstrap account the seed attributes its decisions to",
    "trader_owner": "the trader side holds no grants; each business's primary contact signs in",
}


def _catalogue() -> Any:
    spec = importlib.util.spec_from_file_location("demo_seed_rbac_catalogue", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assignable() -> set[str]:
    """Roles a person may hold: enabled, and not the system's own."""

    return {
        code
        for code, _description, is_system, is_enabled in _catalogue().ROLES
        if is_enabled and not is_system
    }


def test_the_catalogue_is_read() -> None:
    """Guard the guard: a reader returning nothing would make every comparison below vacuous."""

    roles = {code for code, *_ in _catalogue().ROLES}
    assert {"warehouse_operator", "accountant", "system_worker", "support_operator"} <= roles
    assert "warehouse_operator" in _assignable()
    assert "system_worker" not in _assignable()


def test_every_role_a_person_can_hold_has_a_demonstration_account() -> None:
    from app.cli.seed_demo import COLLEAGUES

    seeded = {colleague.role for colleague in COLLEAGUES}
    missing = _assignable() - seeded - COVERED_ELSEWHERE.keys()

    assert missing == set(), (
        f"no demonstration account for {sorted(missing)}: add one to COLLEAGUES in "
        "app/cli/seed_demo.py, or name here what else covers it"
    )


def test_no_demonstration_account_holds_a_role_nobody_should() -> None:
    """Not a system role, and not one the catalogue ships disabled."""

    from app.cli.seed_demo import COLLEAGUES

    wrong = {c.username: c.role for c in COLLEAGUES if c.role not in _assignable()}

    assert wrong == {}, wrong


def test_each_exemption_still_holds() -> None:
    """An exemption whose reason expired reads as coverage while giving none."""

    roles = {code for code, *_ in _catalogue().ROLES}
    assert COVERED_ELSEWHERE.keys() <= roles, sorted(COVERED_ELSEWHERE.keys() - roles)

    # Every revision, not only the first: a later one may grant `user.create`, as later ones
    # have granted other permissions.
    bootstrappers = {
        match.group(1)
        for revision in MIGRATION.parent.glob("*.py")
        for match in re.finditer(
            r'\("([a-z_]+)", "user\.create"\)', revision.read_text(encoding="utf-8")
        )
    }
    assert bootstrappers == {"business_admin"}, (
        f"roles able to bootstrap are now {sorted(bootstrappers)}; the first account need not be "
        "a business_admin any more, so that role needs a demonstration account of its own"
    )
