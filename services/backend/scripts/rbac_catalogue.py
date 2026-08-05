"""Read the approved permission catalogue. One source, no second copy.

`docs/governance/permission_catalog.yaml` is the approved artifact. Copying its
118 permissions and 9 roles into Python would create a second list that drifts
the first time somebody edits one and not the other — and the drift would be a
grant that exists in code and not in governance, or the reverse.

So this parses the file, and the seed writes what it finds.

Three rules the catalogue states and this enforces:

**Doc 05's API spellings are deprecated aliases, not grantable rows.**
DOC-CONFLICT-013 settled that doc 12's identifiers win, because they name the
exact object a permission acts on: `payment_batch_version.approve` binds an
approval to the version that was reviewed, while `payment_batch.approve` names
the mutable container and would let an approval outlive the content it approved.
Seeding an alias as a permission would make the wrong one grantable.

**An alias with no exact canonical target denies.** The catalogue records some as
`unresolved_no_exact_canonical_target`; resolving one by picking the closest
match would silently widen a grant.

**`audit.export` keeps zero default grants**, and `break_glass.*` is seeded for
catalogue completeness with no grants and no activation path — POL-005 disables
break-glass for Phase 1A, including the flag itself.

**This lives in `scripts/`, not in `app/`, and that placement is load-bearing.**
`docs/` is not copied into the container image, so a runtime module reading it
would work in a checkout and fail on start in production — the exact failure
`tests/backend/test_package_is_relocatable.py` was written for after it happened
once. The catalogue is therefore read at authoring time to generate the seed
migration, and the migration carries the resulting data inline. A test compares
the two, so drift between governance and the seed fails in CI rather than
appearing as a permission that exists in one place and not the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CATALOGUE_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "governance"
    / "permission_catalog.yaml"
)

# Roles whose existence the platform depends on rather than an operator choosing
# them. `system_worker` is how background work authors audit rows without holding
# human financial authority.
SYSTEM_ROLES = frozenset({"system_worker"})

# Seeded present but switched off. The catalogue records support_operator as
# disabled by default; enabling it is a deliberate act with its own audit row.
DISABLED_BY_DEFAULT = frozenset({"support_operator"})


@dataclass(frozen=True)
class CataloguePermission:
    code: str
    domain: str
    default_roles: tuple[str, ...]


@dataclass(frozen=True)
class CatalogueRole:
    code: str
    purpose: str
    identity_domain: str

    @property
    def is_system(self) -> bool:
        return self.code in SYSTEM_ROLES

    @property
    def is_enabled(self) -> bool:
        return self.code not in DISABLED_BY_DEFAULT


@lru_cache(maxsize=1)
def _document() -> dict[str, Any]:
    loaded = yaml.safe_load(CATALOGUE_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{CATALOGUE_PATH} does not contain a mapping")
    return loaded


def roles() -> tuple[CatalogueRole, ...]:
    entries = _document()["roles"]
    return tuple(
        CatalogueRole(
            code=code,
            purpose=str(entry.get("baseline_purpose", "")),
            identity_domain=str(entry.get("identity_domain", "")),
        )
        for code, entry in entries.items()
    )


def permissions() -> tuple[CataloguePermission, ...]:
    found: list[CataloguePermission] = []
    for group in _document()["permission_groups"].values():
        domain = str(group.get("domain", ""))
        for code, entry in group.get("permissions", {}).items():
            found.append(
                CataloguePermission(
                    code=code,
                    domain=domain,
                    default_roles=tuple(entry.get("default_roles") or ()),
                )
            )
    return tuple(found)


def deprecated_aliases() -> dict[str, str | None]:
    """Doc 05 spellings mapped to their canonical target, or None where unresolved.

    Returned so a test can assert none of them became a permission row. An alias
    never broadens a grant, and an ambiguous one fails closed.
    """

    aliases = _document()["api_permission_aliases"].get("aliases", {})
    resolved: dict[str, str | None] = {}
    for alias, entry in aliases.items():
        if isinstance(entry, dict):
            target = entry.get("canonical_target")
            resolved[alias] = None if not isinstance(target, str) else target
        else:
            resolved[alias] = entry if isinstance(entry, str) else None
    return resolved
