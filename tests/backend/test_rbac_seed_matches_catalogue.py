"""The seed migration and the approved catalogue must say the same thing.

The migration carries its data inline because `docs/` is not shipped in the
container image — a migration that read the catalogue at runtime would work in a
checkout and fail on every deployment. That inlining creates a second copy, and a
second copy drifts: someone edits governance, the migration keeps the old set,
and a permission exists in one place and not the other with nothing to say so.

This is what says so. It reads both and compares them, so the drift is a CI
failure rather than a discrepancy discovered during an audit.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
MIGRATION = (
    BACKEND_ROOT / "alembic" / "versions" / "20260801_0008_seed_rbac_catalogue.py"
)
# The second migration that seeds permissions. `_0008` has shipped, so editing its list
# would seed nothing on a database that already ran it — DOC-CONFLICT-045's two activation
# permissions therefore arrive in their own revision, and the seeded set is the union.
ACTIVATION_MIGRATION = (
    BACKEND_ROOT / "alembic" / "versions" / "20260816_0014_activation_permissions.py"
)

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.rbac_catalogue import (  # noqa: E402
    deprecated_aliases,
    permissions,
    roles,
)


def load_migration() -> object:
    """Load the revision by path.

    Alembic revisions are not importable as modules — the directory is not a
    package and the filenames are not identifiers.
    """

    return _load(MIGRATION, "seed_rbac")


def load_activation_seed() -> object:
    """The second seeding revision. See `ACTIVATION_MIGRATION`."""

    return _load(ACTIVATION_MIGRATION, "seed_activation_permissions")


def _load(path: Path, name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seed() -> object:
    return load_migration()


class TestTheComparisonIsNotVacuous:
    def test_the_catalogue_has_the_expected_scale(self) -> None:
        """Guard the guard: an empty read would make every comparison below pass."""

        assert len(roles()) == 9
        assert len(permissions()) > 100

    def test_the_migration_carries_data(self, seed: object) -> None:
        assert len(seed.ROLES) == 9  # type: ignore[attr-defined]
        assert len(seed.PERMISSIONS) > 100  # type: ignore[attr-defined]
        assert len(seed.ROLE_PERMISSIONS) > 100  # type: ignore[attr-defined]


class TestSeedMatchesCatalogue:
    def test_the_role_set_is_identical(self, seed: object) -> None:
        catalogue_codes = {role.code for role in roles()}
        seeded_codes = {code for code, _desc, _system, _enabled in seed.ROLES}  # type: ignore[attr-defined]

        assert seeded_codes == catalogue_codes

    def test_the_permission_set_is_identical(self, seed: object) -> None:
        """The seeded set is the union of every migration that seeds permissions.

        Reading only `_0008` reported the catalogue as ahead of the schema when both were
        correct — DOC-CONFLICT-045's two activation permissions are seeded by a later
        revision, and had to be, because editing an applied migration seeds nothing on a
        database that already ran it.
        """

        activation = load_activation_seed()
        catalogue_codes = {permission.code for permission in permissions()}
        seeded_codes = {code for code, _domain in seed.PERMISSIONS}  # type: ignore[attr-defined]
        seeded_codes |= {
            code
            for code, _domain in activation.ACTIVATION_PERMISSIONS  # type: ignore[attr-defined]
        }

        assert seeded_codes == catalogue_codes

    def test_every_default_grant_is_reproduced(self, seed: object) -> None:
        expected = {
            (role_code, permission.code)
            for permission in permissions()
            for role_code in permission.default_roles
        }
        seeded = set(seed.ROLE_PERMISSIONS)  # type: ignore[attr-defined]

        assert seeded == expected

    def test_no_grant_names_a_role_that_does_not_exist(self, seed: object) -> None:
        """A grant to an unknown role is a typo that silently grants nothing."""

        known = {code for code, _desc, _system, _enabled in seed.ROLES}  # type: ignore[attr-defined]
        referenced = {role_code for role_code, _perm in seed.ROLE_PERMISSIONS}  # type: ignore[attr-defined]

        assert referenced <= known


class TestOnlyCanonicalIdentifiersAreSeeded:
    def test_no_deprecated_alias_became_a_permission(self, seed: object) -> None:
        """DOC-CONFLICT-013: doc 12's identifiers win, and the reason is precision.

        `payment_batch_version.approve` binds an approval to the version that was
        reviewed; doc 05's `payment_batch.approve` names the mutable container and
        would let an approval outlive the content it approved. Seeding the alias
        would make the wrong one grantable.
        """

        aliases = set(deprecated_aliases())
        seeded = {code for code, _domain in seed.PERMISSIONS}  # type: ignore[attr-defined]

        assert not (aliases & seeded), (
            f"deprecated API spellings were seeded as grantable permissions: "
            f"{sorted(aliases & seeded)}"
        )

    def test_there_are_deprecated_aliases_to_exclude(self) -> None:
        """Otherwise the check above passes against an empty set."""

        assert len(deprecated_aliases()) > 10

    def test_some_aliases_have_no_canonical_target(self) -> None:
        """Those deny rather than resolving to the closest match.

        Picking a near match would silently widen a grant.
        """

        unresolved = [name for name, target in deprecated_aliases().items() if target is None]

        assert unresolved, "no unresolved aliases found; the fail-closed path is untested"


class TestRestrictedPermissions:
    def test_audit_export_has_no_default_grants(self, seed: object) -> None:
        """Kept separate from `audit.read` deliberately: reading history and
        removing it from the system are different authorities."""

        granted = [
            role for role, permission in seed.ROLE_PERMISSIONS  # type: ignore[attr-defined]
            if permission == "audit.export"
        ]

        assert granted == []

    def test_break_glass_is_seeded_with_no_grants(self, seed: object) -> None:
        """POL-005 disables break-glass for Phase 1A including the flag itself.

        The rows exist for catalogue completeness; there is no activation path,
        and no role holds them.
        """

        seeded = {code for code, _domain in seed.PERMISSIONS}  # type: ignore[attr-defined]
        assert {"break_glass.activate", "break_glass.review"} <= seeded

        granted = [
            (role, permission)
            for role, permission in seed.ROLE_PERMISSIONS  # type: ignore[attr-defined]
            if permission.startswith("break_glass.")
        ]
        assert granted == []

    def test_there_is_no_super_admin_role(self, seed: object) -> None:
        """A role that holds everything defeats separation of duties by existing."""

        codes = {code for code, _desc, _system, _enabled in seed.ROLES}  # type: ignore[attr-defined]

        assert "super_admin" not in codes


class TestRoleFlags:
    def test_support_operator_is_seeded_disabled(self, seed: object) -> None:
        """Enabling it is a deliberate act rather than the default."""

        flags = {
            code: enabled for code, _desc, _system, enabled in seed.ROLES  # type: ignore[attr-defined]
        }

        assert flags["support_operator"] is False

    def test_system_worker_is_marked_a_system_role(self, seed: object) -> None:
        """So an admin screen can refuse to delete it without a hardcoded list."""

        flags = {
            code: is_system for code, _desc, is_system, _enabled in seed.ROLES  # type: ignore[attr-defined]
        }

        assert flags["system_worker"] is True
        assert flags["manager"] is False
