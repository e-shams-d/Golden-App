"""M4's Definition of Done, as a gate that fails when a later milestone breaks it.

Covers: TRACE-DOD-003, TRACE-DOD-004, TRACE-DOD-005, TRACE-DOD-006, TRACE-M4-001.

`15_Agent_Implementation_Plan.md:730`:

    M4 is complete when every later module can reference a stable `FileObject` and a
    stable bank configuration version without directly handling storage paths or mutable
    bank settings.

Like M3's, this names a **property**, and the property is about code that does not exist
yet — "every later module" is M5 through M12, and nothing here can test M5's behaviour.
What can be tested is the boundary that makes the property true, and it decomposes into
three mechanical claims plus the ledger that says nothing is owed.

A promise made to five future milestones with no gate is a comment.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APP = REPOSITORY_ROOT / "services" / "backend" / "app"
CONTRACT = REPOSITORY_ROOT / "services" / "backend" / "openapi" / "v1.json"

# The three column names that are a storage address.
STORAGE_ADDRESS_NAMES = frozenset({"storage_key", "storage_bucket", "storage_provider"})

# The packages that own storage. Everything else must go through them.
INSIDE = ("storage/", "files/")

# Modules outside those packages that legitimately touch the backend, and why. Asserted as
# an **exact** set below rather than merely excluded: an allowlist that can grow silently
# is not a boundary, it is a habit.
#
#   core/runtime.py          constructs the backend into the runtime container
#   observability/health.py  probes it for readiness
#   db/models/file_object.py declares the three columns; this is where the address is
#                            defined, and a boundary cannot exclude its own definition
#   cli/reconcile_storage.py renders an operator report. `Finding` says why it may:
#                            "an operator resolving a mismatch needs to know which object
#                            it is ... a finding is an operator artifact, not an API
#                            payload". It is behind a shell, not a route.
#
# `api/v1/files.py` is deliberately absent. It served bytes with
# `runtime.storage.open(record.storage_key)` until this slice, and this gate is what found
# it: the code was correct and the boundary was not. `app/files/download.py` owns that now.
INFRASTRUCTURE = frozenset(
    {
        "core/runtime.py",
        "observability/health.py",
        "db/models/file_object.py",
        "cli/reconcile_storage.py",
    }
)


def _modules() -> list[Path]:
    return sorted(path for path in APP.rglob("*.py") if "__pycache__" not in path.parts)


def _relative(path: Path) -> str:
    return path.relative_to(APP).as_posix()


def _names(path: Path) -> set[str]:
    """Identifiers a module uses, from the parsed source rather than a substring search.

    A name inside a docstring is documentation. Counting it would let this file's own
    explanation of the rule violate the rule, which is the shape
    `test_reserved_scan_status.py` and slice 10's storage scan both had to correct.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


def test_the_scan_finds_the_application() -> None:
    """Guard the guard: an empty scan makes every assertion below vacuous."""

    assert len(_modules()) > 60


def test_no_module_outside_the_file_service_handles_a_storage_address() -> None:
    """TRACE-DOD-003, the first of the DoD's three claims.

    A later module references a `FileObject` by id and asks this package for its bytes. It
    never learns where they are, so a change of storage provider — ADR-003 is still open —
    touches `app/storage/` and nothing else.
    """

    offenders: dict[str, set[str]] = {}
    for path in _modules():
        relative = _relative(path)
        if relative.startswith(INSIDE) or relative in INFRASTRUCTURE:
            continue
        used = _names(path) & STORAGE_ADDRESS_NAMES
        if used:
            offenders[relative] = used

    assert offenders == {}, (
        "these modules handle a storage address and are outside app/storage/ and "
        f"app/files/:\n{offenders}\nAsk the file service for the bytes instead; it "
        "returns an iterator and keeps the address."
    )


def test_the_infrastructure_allowlist_is_exactly_what_is_recorded() -> None:
    """The exclusion above is only meaningful if it cannot grow quietly.

    Guard-the-guard in both directions: an empty allowlist would make the test above pass
    for the wrong reason, and a grown one would let a new module opt out of the boundary
    by editing a set rather than by arguing for it.
    """

    recorded = frozenset(
        {
            "core/runtime.py",
            "observability/health.py",
            "db/models/file_object.py",
            "cli/reconcile_storage.py",
        }
    )
    assert recorded == INFRASTRUCTURE
    for module in INFRASTRUCTURE:
        assert (APP / module).exists(), f"the allowlist names {module}, which is gone"


def test_no_published_schema_carries_a_storage_address() -> None:
    """TRACE-DOD-004.

    Read from the generated contract rather than from the response models, so the floor is
    a rule over an artifact the OpenAPI gate already holds equal to the application. A
    field added to any schema — including one no test exercises — fails here.
    """

    document = json.loads(CONTRACT.read_text(encoding="utf-8"))
    schemas = document["components"]["schemas"]
    assert len(schemas) > 20, "the contract looks empty; this gate would pass vacuously"

    offenders = {
        name: sorted(STORAGE_ADDRESS_NAMES & set(schema.get("properties", {})))
        for name, schema in schemas.items()
        if STORAGE_ADDRESS_NAMES & set(schema.get("properties", {}))
    }

    assert offenders == {}, (
        f"these published schemas expose a storage address: {offenders}. "
        "`command_catalog.yaml` states `raw_storage_keys_never_returned`."
    )


def test_every_catalogued_purpose_has_an_ownership_resolver() -> None:
    """TRACE-DOD-005, the second claim.

    A later module attaches files to its own resource by registering a resolver for its
    category, and inherits every guard below it. The registry denies a category it does not
    know — which is the safe direction and also an invisible one, because a file nobody can
    download looks like a storage fault. This turns it into a failing test instead.
    """

    from app.files.ownership import categories_without_a_resolver
    from app.files.purposes import purpose_ids

    assert len(purpose_ids()) >= 5
    assert categories_without_a_resolver() == frozenset()


def test_bank_configuration_offers_no_rule_without_its_version() -> None:
    """TRACE-DOD-006, the third claim.

    "Without directly handling mutable bank settings" is already structurally true —
    `bank_profiles` carries identity and every operational rule lives on an immutable
    version. This keeps it true at the service boundary: a caller holding a transfer limit
    without the version it came from cannot reproduce the decision it made.
    """

    import inspect

    from app.bankconfig import resolution

    # Defined in the module, not merely present in its namespace: `select` and friends are
    # imported and returning a `Select` is not a claim about bank rules. The first version
    # of this failed on sqlalchemy's `select`, which is the difference between "what this
    # module offers" and "what it can see".
    public = [
        name
        for name, value in vars(resolution).items()
        if inspect.isfunction(value)
        and not name.startswith("_")
        and value.__module__ == resolution.__name__
    ]
    assert "resolve_active_version" in public

    for name in public:
        returns = inspect.signature(getattr(resolution, name)).return_annotation
        assert returns in (None, "None", "ResolvedVersion", inspect.Signature.empty), (
            f"{name} returns {returns!r}; an operational rule must travel with the "
            "version id that produced it"
        )

    assert "version_id" in resolution.ResolvedVersion.__dataclass_fields__


def test_nothing_is_owed_for_m4() -> None:
    """TRACE-M4-001.

    The milestone is complete when nothing is owed, and the ledger is what says so. An
    obligation still in `PENDING` is one a slice promised and no test discharges — which is
    exactly the state this whole traceability apparatus exists to make visible rather than
    survivable.
    """

    from test_traceability import PENDING, plans

    m4 = next(plan for plan in plans() if plan.name.startswith("M4"))
    assert m4.exists()

    # Every M4 obligation is either cited by a test or recorded as a permanent gap with a
    # reason. `PENDING` is for work not yet written, and M4 has none left.
    m4_prefixes = ("FILE-", "BANK-", "OPS-RECON", "OPS-LIMIT", "OPS-BANKCFG", "UI-FILE", "TRACE-")
    owed = sorted(
        identifier
        for identifier in PENDING
        if identifier.startswith(m4_prefixes)
    )

    assert owed == [], f"M4 obligations still owed: {owed}"


def test_every_definition_of_done_obligation_is_cited_by_this_file() -> None:
    """Guard the guard for the whole file.

    The DoD decomposes into a fixed set of claims, and if one were dropped — because it
    became inconvenient, or because a refactor removed the test carrying it — the
    remaining tests would pass and the milestone would still look complete.

    **Derived from the plan, not listed here.** A hand-written list of claims is a list
    somebody deletes a line from, and the first version of this was exactly that: a
    `parametrize` whose cases could be removed one at a time, each removal making one
    fewer test run rather than one test fail. The negative control caught it. The
    repository already knows this shape — `test_admin_users.py` says "a parametrised
    negative that lost a case would still pass" and derives its expectation from the
    committed contract for the same reason.

    So the obligations come from the M4 plan's own slice-11 section, and every one of them
    must be named in this file.
    """

    plan = REPOSITORY_ROOT / "docs" / "handoff" / "M4_IMPLEMENTATION_PLAN.md"
    text = plan.read_text(encoding="utf-8")

    marker = "## Slice 11"
    assert marker in text, "the M4 plan no longer has a slice 11 section to read"
    section = text[text.index(marker) :]

    obligations = sorted(set(re.findall(r"\bTRACE-(?:DOD|M4)-\d+\b", section)))
    assert len(obligations) >= 5, (
        f"only parsed {obligations} from the plan's slice 11; the section's shape changed "
        "and this guard is no longer reading the promise"
    )

    # Inside a test, not anywhere in the file. The module's own "Covers:" header names
    # every obligation, so a whole-file search is satisfied by the header alone — the
    # citation-as-coverage hazard this repository keeps meeting, here in the gate that
    # certifies a milestone. The negative control caught it: deleting an id from a test's
    # docstring changed nothing.
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    inside_tests = " ".join(
        ast.unparse(node)
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    )

    missing = [identifier for identifier in obligations if identifier not in inside_tests]

    assert missing == [], (
        f"the M4 plan states {missing} for slice 11 and no test in this file names them. "
        "Restore the test rather than editing the plan: the plan is what says which "
        "claims M4 promised."
    )
