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

This module holds the names and nothing else. It deliberately does **not** read
the catalogue file. An earlier version resolved it as
``Path(__file__).resolve().parents[4] / "docs" / ...``, which is correct in the
repository and raises IndexError inside the container, where the package sits at
``/app/app`` and has no fourth parent — and `docs/` is not shipped in the image
anyway. The application crashed on import the moment a router pulled this in.

The rule that prevents the next one: runtime code never reads a repository
document. Checking these names against governance is a test's job, and
`tests/backend/test_name_registry_and_errors.py` does it from the repository,
where the file certainly exists.
"""

from __future__ import annotations

from dataclasses import dataclass


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

# --- M3 slice 8: the trader lifecycle -------------------------------------
#
# The four audit actions below ARE in the approved catalogue (`:15-18`). Their
# outbox event types are not: `audit_outbox_catalog.yaml:68-80` lists eleven
# events and none of them concerns a trader's approval state.
#
# That is a real gap rather than an oversight on our side.
# `05_API_Specification.md:878` states that role changes, suspension and
# reactivation create audit **and outbox** events, so an event is required by the
# API contract and unnamed by the catalogue. The catalogue is
# `provisional_pending_m0_approval`, so implementing a name is permitted; what is
# not permitted is doing it silently, which is what `provisional_reason` is for.

_OUTBOX_GAP = (
    "05_API_Specification.md:878 requires an outbox event for these commands and "
    "audit_outbox_catalog.yaml:68-80 names none for the trader lifecycle. The "
    "catalogue is provisional_pending_m0_approval so the name may be implemented, "
    "but it must be renamed to whatever M0 approves. Raised for the register."
)

REGISTER_TRADER = CommandNames(
    audit_action="trader.registered",
    outbox_event_type="TraderRegistered",
    catalogued=False,
    provisional_reason=(
        "Self-registration is not in the catalogue's audit action list either: it "
        "records the actions the center takes on a trader, and a trader creating "
        "itself is a fifth event nobody enumerated. " + _OUTBOX_GAP
    ),
)

APPROVE_TRADER = CommandNames(
    audit_action="trader.approved",
    outbox_event_type="TraderApproved",
    catalogued=False,
    provisional_reason=_OUTBOX_GAP,
)

REJECT_TRADER = CommandNames(
    audit_action="trader.rejected",
    outbox_event_type="TraderRejected",
    catalogued=False,
    provisional_reason=_OUTBOX_GAP,
)

SUSPEND_TRADER = CommandNames(
    audit_action="trader.suspended",
    outbox_event_type="TraderSuspended",
    catalogued=False,
    provisional_reason=_OUTBOX_GAP,
)

REACTIVATE_TRADER = CommandNames(
    audit_action="trader.reactivated",
    outbox_event_type="TraderReactivated",
    catalogued=False,
    provisional_reason=_OUTBOX_GAP,
)

# Credential changes. Deliberately audited as well as recorded in `auth_events`:
# a security event explains a refusal, while an administrator resetting somebody
# else's password is an authorised change to another person's account, which is
# what `audit_logs` is for. Neither name is catalogued.
CHANGE_OWN_PASSWORD = CommandNames(
    audit_action="credential.changed_own",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=(
        "audit_outbox_catalog.yaml enumerates financial-flow actions and no "
        "credential lifecycle. No outbox event: nothing outside the platform acts "
        "on somebody changing their own password, and publishing it would put a "
        "credential event on a queue for no consumer."
    ),
)

RESET_ADMIN_PASSWORD = CommandNames(
    audit_action="credential.reset_by_administrator",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=(
        "Same catalogue gap. Audited rather than only recorded as a security event "
        "because an administrator setting another person's credential is an "
        "authorised change to an account they do not own — doc 12:642 requires "
        "alerting on comparable grants, and an audit row is what an alert reads."
    ),
)


ALL_COMMAND_NAMES: tuple[CommandNames, ...] = (
    RENAME_CENTER_PROFILE,
    REGISTER_TRADER,
    APPROVE_TRADER,
    REJECT_TRADER,
    SUSPEND_TRADER,
    REACTIVATE_TRADER,
    CHANGE_OWN_PASSWORD,
    RESET_ADMIN_PASSWORD,
)
