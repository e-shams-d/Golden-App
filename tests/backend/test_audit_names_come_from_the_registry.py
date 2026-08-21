"""No command writes an audit action or an outbox event as a literal, and no entry hides.

`app/audit/registry.py` exists for one reason, which its own docstring states: every name in
`audit_outbox_catalog.yaml` is `provisional_pending_m0_approval` and **will be renamed**. Without
the indirection a rename is a call-site sweep across every command, and any name that reached a
database column needs a migration on top. So "call sites reference a `CommandNames` entry, never
a literal".

Nothing checked that. M6 slices 2 and 3 shipped `app/commands/payment_batch.py` with four
module-level string literals — `"payment_batch.created"`, `"payment_batch_version.finalized"`,
`"PaymentBatchVersionReadyForApproval"` — and every gate stayed green, because the convention
lived in a docstring and the docstring is not executable.

**The second half is the one that would have caught more.** `ALL_COMMAND_NAMES` is the tuple
`test_name_registry_and_errors.py` iterates, and it is the *only* thing checking any name against
the catalogue. Three M5 entries — `BEGIN_REVIEW`, `RETURN_FOR_CORRECTION`,
`MARK_ELIGIBLE_FOR_BATCHING` — were defined in the registry and left out of that tuple, so their
`catalogued=True` claims were never verified against the file. A gate whose input is incomplete
is the same shape as a mechanism with no caller, and it is harder to notice: the gate passes.

Both halves are asserted on the AST rather than by importing and comparing values, because a
literal that has been *assigned to a constant* is still a literal — `AUDIT_ACTION = "x.y"` and
`action="x.y"` are the same defect, and only the source shows the difference between them and
`action=SOME_ENTRY.audit_action`.

Covers: TRACE-AUDIT-001.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "services" / "backend"
COMMANDS = BACKEND / "app" / "commands"
REGISTRY = BACKEND / "app" / "audit" / "registry.py"

# The shape of a catalogued name. Audit actions are dotted lowercase; outbox events are
# PascalCase. Both conventions are deliberate and `test_name_registry_and_errors.py` pins them,
# so the same two shapes are what to look for in a command module.
#
# Deliberately narrow. A dotted lowercase string is common — `"app.core.time"`, a log key, a
# metadata schema name — so matching every one of them would produce a wall of false positives
# and this file would be deleted within a week. What is matched instead is a string in the
# *position* of an audit action or an event type: the `action=`, `event_type=` and
# `audit_action=` keywords, plus any assignment whose name says what it holds.
# Split by keyword, because `event_type=` is used by **two** vocabularies and only one of them
# belongs here. `app/audit/registry.py` pins the distinction and this gate reuses it rather than
# inventing an exemption list: audit actions are dotted lowercase, outbox event types are
# PascalCase, and `AuthEvent`'s security event types are dotted lowercase in a third namespace
# with its own words (`step_up.rejected`, `role.high_risk_permission_granted`).
#
# So `action=` and `audit_action=` flag any literal — those keywords have one meaning. For
# `event_type=`, only a PascalCase literal is an outbox event; a dotted lowercase one is a
# security event and is none of this file's business. The first version of this gate flagged both
# and reported two false positives in `role_permissions.py`, which is how the split got written.
ACTION_KEYWORDS = frozenset({"action", "audit_action"})
EVENT_KEYWORDS = frozenset({"event_type", "outbox_event_type"})

ACTION_HINTS = ("AUDIT_ACTION", "AUDIT_NAME")
EVENT_HINTS = ("OUTBOX_EVENT", "EVENT_TYPE")


def _is_outbox_shaped(value: str) -> bool:
    """PascalCase, which is what `audit_outbox_catalog.yaml`'s `outbox_events` all are.

    A dotted name is not one, and neither is an empty string. Deliberately not a regex over the
    whole catalogue: the point is the *shape* the convention fixes, so a name added later is
    covered without this file being edited.
    """

    return bool(value) and value[0].isupper() and "." not in value and "_" not in value


APPLICATION = BACKEND / "app"

# Directories that never hold an audit name and would otherwise be scanned for nothing. Narrow
# on purpose: the first version of this gate looked only at `app/commands/` and missed
# `bank_profile.version_activated`, which lives in `app/bankconfig/resolution.py` — activation is
# a configuration resolution rather than a command, and the defect does not care.
#
# `audit/` is excluded because the registry itself is where the names legitimately are literals,
# and `db/models/` because a column default is not a call site.
EXCLUDED_DIRECTORIES = frozenset({"audit", "models"})


def scanned_modules() -> list[Path]:
    """Every application module that could carry an audit name.

    The whole of `app/`, minus the registry and the models. Scoping this to `app/commands/` is
    what let one literal survive the gate's first run, and "commands are where audit happens" is
    a convention nothing enforces — `resolution.py` writes an audit row and is not a command.
    """

    modules = sorted(
        path
        for path in APPLICATION.rglob("*.py")
        if path.name != "__init__.py"
        and not any(part in EXCLUDED_DIRECTORIES for part in path.relative_to(APPLICATION).parts)
    )
    assert modules, f"no modules found under {APPLICATION}; this gate would assert nothing"
    assert any(path.parent.name == "commands" for path in modules), (
        "no command modules in the scan; the layout changed and this gate is looking in the "
        "wrong place"
    )
    return modules


def _literal_offences(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offences: list[str] = []

    for node in ast.walk(tree):
        # `action="payment_batch.created"` — a literal in the position of a name.
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if not isinstance(keyword.value, ast.Constant):
                    continue
                value = keyword.value.value
                if not isinstance(value, str):
                    continue
                if keyword.arg in ACTION_KEYWORDS or (
                    keyword.arg in EVENT_KEYWORDS and _is_outbox_shaped(value)
                ):
                    offences.append(
                        f"{path.name}:{node.lineno} passes {keyword.arg}={value!r} as a literal"
                    )

        # `AUDIT_ACTION = "payment_batch.created"` — a literal one indirection away, which is
        # what M6 slices 2 and 3 actually did. Assigning it to a constant does not make it come
        # from the registry; it makes the rename sweep one line longer per module.
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if not (
                    isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    continue
                value = node.value.value
                if any(hint in target.id for hint in ACTION_HINTS) or (
                    any(hint in target.id for hint in EVENT_HINTS)
                    and _is_outbox_shaped(value)
                ):
                    offences.append(
                        f"{path.name}:{node.lineno} assigns {target.id} = {value!r} as a literal"
                    )

    return offences


def test_no_command_module_writes_an_audit_name_as_a_literal() -> None:
    """Every audit action and outbox event in a command comes from the registry.

    The failure message says what to do, because the fix is always the same: add a
    `CommandNames` entry and reference it. A name that genuinely has no catalogue entry is not an
    exception to this — that is what `catalogued=False` plus `provisional_reason` is for, and it
    is the only place a reason can be recorded next to the name it excuses.
    """

    offences = [offence for path in scanned_modules() for offence in _literal_offences(path)]

    assert offences == [], (
        "audit names must come from `app/audit/registry.py`, because they are "
        "`provisional_pending_m0_approval` and will be renamed — a literal turns that rename "
        "into a call-site sweep:\n"
        + "\n".join(f"  {offence}" for offence in offences)
        + "\nAdd a CommandNames entry (with `catalogued=False` and a reason if the catalogue is "
        "silent) and reference its `.audit_action` / `.outbox_event_type`."
    )


def _registry_tree() -> ast.Module:
    return ast.parse(REGISTRY.read_text(encoding="utf-8"))


def defined_entries() -> set[str]:
    """Every module-level `X = CommandNames(...)` in the registry."""

    names: set[str] = set()
    for node in _registry_tree().body:
        if not isinstance(node, ast.Assign):
            continue
        if not (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "CommandNames"
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def exported_entries() -> set[str]:
    """Whatever `ALL_COMMAND_NAMES` actually contains."""

    for node in _registry_tree().body:
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
        )
        if not any(
            isinstance(target, ast.Name) and target.id == "ALL_COMMAND_NAMES"
            for target in targets
        ):
            continue
        value = node.value
        assert isinstance(value, ast.Tuple), "ALL_COMMAND_NAMES is no longer a tuple literal"
        return {
            element.id for element in value.elts if isinstance(element, ast.Name)
        }
    raise AssertionError("ALL_COMMAND_NAMES is not defined in the registry")


def test_every_registry_entry_is_in_the_tuple_the_gate_reads() -> None:
    """The gap that let three M5 names go unchecked against the catalogue.

    `ALL_COMMAND_NAMES` is the only input `test_name_registry_and_errors.py` has, so an entry
    absent from it is an entry whose `catalogued=True` claim nobody verified — and the claim is
    exactly the thing that could be a typo. Three of M5's seven were in that state for a whole
    milestone.

    Read from the AST rather than by importing, so a name defined but never referenced is still
    seen. Importing would give the same answer today and would stop giving it the moment somebody
    guards a definition behind a conditional.
    """

    defined = defined_entries()
    exported = exported_entries()

    assert defined, "no CommandNames entries found; the parser has stopped seeing them"
    missing = sorted(defined - exported)
    assert missing == [], (
        f"these registry entries are not in ALL_COMMAND_NAMES: {missing}. That tuple is the only "
        "thing checking a name against `audit_outbox_catalog.yaml`, so an entry outside it "
        "claims to be catalogued and nobody verifies the claim."
    )

    stray = sorted(exported - defined)
    assert stray == [], (
        f"ALL_COMMAND_NAMES names {stray}, which is not a CommandNames defined in this module"
    )


@pytest.mark.parametrize(
    "expected",
    [
        "CREATE_PAYMENT_BATCH",
        "FINALIZE_PAYMENT_BATCH_VERSION",
        "CREATE_PAYMENT_BATCH_VERSION",
        "CANCEL_PAYMENT_BATCH",
        "BEGIN_REVIEW",
        "RETURN_FOR_CORRECTION",
        "MARK_ELIGIBLE_FOR_BATCHING",
    ],
)
def test_the_names_this_gate_was_written_for_are_present(expected: str) -> None:
    """The five M6 entries and the three M5 entries that were missing.

    Named individually rather than counted, so a future refactor that renames one has to decide
    what to do about it here rather than silently dropping the coverage. A count would pass on
    any eight.
    """

    assert expected in defined_entries(), f"{expected} is no longer defined in the registry"
    assert expected in exported_entries(), f"{expected} is no longer in ALL_COMMAND_NAMES"
