"""The bank's own document never reaches a trader, on any route or through any file id.

`SEC-PUBLICATION-001`. §17 `:1185` lists it among the ten M9 tests in five words — "full bundle
never reaches trader APIs or files" — and `15_Agent_Implementation_Plan.md:721` named the same
failure as an M4 case: a trader cannot download an internal bank bundle.

**Scanned over the whole trader surface rather than over the publication route.** A bundle id
added to a trader response is not a mistake somebody makes in the module that was reviewed for it;
it is one somebody makes wherever a bundle id happens to be in scope. So the test finds every
route whose path is trader-owned and checks all of them, and it finds them by reading the routes
rather than from a list a later slice would forget to extend.

M9 slice 5 is the first slice with something to protect here — before a publication existed, a
trader had nothing to be shown. Slice 6 adds three more trader routes and inherits this file
unchanged, which is the point of scanning rather than enumerating.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
API = REPO / "services" / "backend" / "app" / "api" / "v1"
COMMAND = (
    REPO / "services" / "backend" / "app" / "commands" / "payment_publication.py"
)

# `05_API_Specification.md` §20.4 and §21: everything a trader reaches about themselves lives
# under this prefix. A route outside it that a trader could reach would be a different bug, and
# `test_permission_guards.py` is what catches that one.
TRADER_PREFIX = "/me/trader"

# The columns and the model that mean "the bank's mixed document, containing every trader's
# results". `receipt_segments.segment_file_id` — the crop — is deliberately absent: it is the one
# file id a trader may be given, and the whole design of M8 was to produce it.
BUNDLE_NAMES = (
    "BankResultBundle",
    "bank_result_bundle_id",
    "bank_result_bundle_file_id",
    "source_file_id",
)


def _module_paths(tree: ast.Module) -> list[str]:
    """Every string a route decorator or an `APIRouter(prefix=...)` declares in this module."""

    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                found.append(str(keyword.value.value))
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                found.append(argument.value)
    return found


def _trader_facing_modules() -> list[Path]:
    modules: list[Path] = []
    for path in sorted(API.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(TRADER_PREFIX in value for value in _module_paths(tree)):
            modules.append(path)
    return modules


def _referenced_names(path: Path) -> set[str]:
    """Every identifier and attribute name the module mentions.

    An AST walk rather than a substring search, so the prose in a docstring explaining why a
    bundle must not appear does not itself count as a bundle appearing — the mistake this
    repository has already made twice, once with an obligation id and once with the comment
    explaining that collision.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name.rsplit(".", 1)[-1])
            if node.asname:
                names.add(node.asname)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            # A key in a response dictionary is a string, not a name, and is exactly how a
            # bundle id would be handed out. The length bound is what keeps a docstring
            # explaining the rule from counting as a breach of it.
            and len(node.value) <= 64
        ):
            names.add(node.value)
    return names


def test_the_trader_surface_exists_and_is_found_by_reading_routes() -> None:
    """The scan below is worthless if it matches nothing, so this asserts it matches something.

    A gate whose input is empty passes — the failure this project has hit more than any other.
    """

    modules = _trader_facing_modules()
    assert modules, (
        f"no module under {API} declares a route beneath {TRADER_PREFIX}. Either the trader "
        "surface moved and this test must follow it, or the scan below is checking nothing."
    )


def test_no_trader_route_module_mentions_the_bank_bundle() -> None:
    """§17 `:1185`. The bundle is every trader's results in one document."""

    offences: list[str] = []
    for path in _trader_facing_modules():
        names = _referenced_names(path)
        for banned in BUNDLE_NAMES:
            if banned in names:
                offences.append(f"{path.name} references {banned}")

    assert offences == [], (
        f"{offences}. `15_Agent_Implementation_Plan.md:721` makes this an explicit test: a trader "
        "cannot download an internal bank bundle. What a trader may see is the crop M8 cut out of "
        "it — `receipt_segments.segment_file_id` — which is a different file with its own row."
    )


def test_the_publication_snapshot_reads_only_the_crop() -> None:
    """The same rule one level in: the file id that *enters* a publication.

    The route scan above cannot see this, because the publication is built in a command and only
    the resulting payload crosses into a response. `04_Database_Schema.md` §12.5 gives a segment
    three file ids and only one of them is safe to publish.
    """

    tree = ast.parse(COMMAND.read_text(encoding="utf-8"))
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    offenders = sorted(name for name in BUNDLE_NAMES if name in attributes)
    assert offenders == [], (
        f"app/commands/payment_publication.py reads {offenders} off a segment. Only "
        "`segment_file_id` may reach a publication; a fallback to any of these is precisely how "
        "a bundle would reach a trader while every route test still passed."
    )
    assert "segment_file_id" in attributes, (
        "the publication no longer reads `segment_file_id`, so either it publishes no evidence at "
        "all or it found the file somewhere else. Both need this test rewritten, not deleted."
    )
