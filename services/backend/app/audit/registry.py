"""One place that decides what a command's audit action and outbox event are called.

Every name in `docs/governance/audit_outbox_catalog.yaml` is marked
`provisional_pending_m0_approval`. They will be renamed. Without this
indirection a rename would be a call-site sweep across every command, and any
name that had reached a database column would need a migration on top.

So call sites reference a `CommandNames` entry, never a literal. A rename becomes
one edit here.

Two conventions live side by side and are never normalised by a shared helper:
audit actions are dotted lowercase, outbox event types are PascalCase. A single
normaliser would look tidy and would silently rewrite one of them at the M0
freeze, which is the moment both must stay exactly as approved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = (
    Path(__file__).resolve().parents[4] / "docs" / "governance" / "audit_outbox_catalog.yaml"
)


@dataclass(frozen=True)
class CommandNames:
    """What one command records and publishes.

    `catalogued` says whether these names appear in the approved catalogue. It is
    not decoration: a name that is *not* there must be declared so deliberately,
    with a reason, because the alternative is a typo silently becoming a
    permanent audit action string that no governance document mentions.
    """

    audit_action: str
    outbox_event_type: str | None
    catalogued: bool
    provisional_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.catalogued and not self.provisional_reason:
            raise ValueError(
                f"{self.audit_action!r} is not in the approved catalogue and gives no "
                "reason; an uncatalogued name must say why it is acceptable"
            )
        if self.catalogued and self.provisional_reason:
            raise ValueError(
                f"{self.audit_action!r} is catalogued, so it needs no provisional reason"
            )


# The exemplar command. `center_profile` is the M2 aggregate that exists to prove
# the transaction machinery — it is not a Phase 1A financial flow, so the
# catalogue does not mention it and should not be edited to add it: that file is
# an approved M0 artifact under a checksum chain, and extending it is an owner
# decision rather than a side effect of writing a command.
RENAME_CENTER_PROFILE = CommandNames(
    audit_action="center_profile.renamed",
    outbox_event_type="CenterProfileRenamed",
    catalogued=False,
    provisional_reason=(
        "center_profile is the M2 exemplar aggregate, not a Phase 1A financial flow. "
        "audit_outbox_catalog.yaml covers the financial flows and is an approved M0 "
        "artifact under a checksum chain; adding an entry is an owner decision."
    ),
)

ALL_COMMAND_NAMES: tuple[CommandNames, ...] = (RENAME_CENTER_PROFILE,)


@lru_cache(maxsize=1)
def catalog() -> dict[str, object]:
    loaded: object = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{CATALOG_PATH} does not contain a mapping")
    return {str(key): value for key, value in loaded.items()}


def catalogued_audit_actions() -> frozenset[str]:
    actions = catalog()["audit_actions"]
    assert isinstance(actions, list)
    return frozenset(str(action) for action in actions)


def catalogued_outbox_events() -> frozenset[str]:
    events = catalog()["outbox_events"]
    assert isinstance(events, list)
    return frozenset(str(event) for event in events)
