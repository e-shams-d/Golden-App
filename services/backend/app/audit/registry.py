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

_FILE_LIFECYCLE_OUTBOX_GAP = (
    "`audit_outbox_catalog.yaml:107` lists its own open item: complete events for "
    "trader rejection/suspension, **file lifecycle**, bank import, gold settlement and "
    "legal-hold release. So the catalogue records that no file-lifecycle event name has "
    "been approved, and this is one. The name may be implemented under the catalogue's "
    "`provisional_pending_m0_approval` status and must be renamed to whatever M0 "
    "approves; `:106` additionally leaves PascalCase against a dotted convention open, "
    "so the spelling here follows the existing `TraderRegistered` form rather than "
    "inventing a second."
)

UPLOAD_FILE = CommandNames(
    audit_action="file.uploaded",
    # No outbox event. Preview dispatch has its own name below, and an upload event has
    # no consumer at all — emitting one would be a message with no reader, which is the
    # shape this milestone is deliberately not repeating.
    outbox_event_type=None,
    # Catalogued as of M4 slice 1, which added `file.upload` to `command_catalog.yaml`
    # under DOC-CONFLICT-046: document 05 defines `POST /api/v1/files` and the catalogue
    # had no entry for it, so the mutation every other upload builds on carried no
    # idempotency or audit contract at all.
    catalogued=True,
)

REQUEST_FILE_PREVIEW = CommandNames(
    # Not a command anybody calls: it is the dispatch an upload emits when the file it
    # finalised can have a preview rendered. The audit action is the upload's own, so
    # this entry exists for the event name and its reason.
    audit_action="file.uploaded",
    outbox_event_type="FilePreviewRequested",
    catalogued=False,
    provisional_reason=_FILE_LIFECYCLE_OUTBOX_GAP,
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

# The beneficiary lifecycle. The catalogue's `audit_actions` list runs from
# `auth.*` through the payment and bank flows and names **no beneficiary action at
# all** — not created, not updated, not deactivated. That is a wider gap than the
# trader one above, where four of five names exist.
_BENEFICIARY_CATALOGUE_GAP = (
    "audit_outbox_catalog.yaml names no beneficiary action of any kind. "
    "12_Security_RBAC_Audit.md:1635 requires an audit trail for the commands behind "
    "governed permissions, and `beneficiary.create`, `beneficiary.update_future` and "
    "`beneficiary.deactivate` are three of them, so the actions are recorded under the "
    "catalogue's `provisional_pending_m0_approval` status and must be renamed to "
    "whatever M0 approves. Raised for the register."
)

# No outbox event on any of the three. Nothing outside the platform acts on a
# trader editing its own address book, and a beneficiary carries a name, an IBAN and
# optionally a national id — publishing that would put personal data on a queue for
# no consumer, which is the reasoning `RECOVER_ADMIN_PASSWORD` already applies and
# `_publish` in `trader_lifecycle` applies to the phone number.
CREATE_BENEFICIARY = CommandNames(
    audit_action="beneficiary.created",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_BENEFICIARY_CATALOGUE_GAP,
)

UPDATE_BENEFICIARY = CommandNames(
    audit_action="beneficiary.updated",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_BENEFICIARY_CATALOGUE_GAP,
)

DEACTIVATE_BENEFICIARY = CommandNames(
    audit_action="beneficiary.deactivated",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_BENEFICIARY_CATALOGUE_GAP,
)

# The request lifecycle. Unlike the beneficiary names above, two of these **are** in
# the catalogue: `payment_request.created` and `payment_request.cancelled` are both in
# `audit_outbox_catalog.yaml`'s `audit_actions`. The catalogue enumerates the financial
# flow, and a payment request is the financial flow.
#
# No outbox event on either, and that is the gap rather than the name. The catalogue's
# own open item at `:107` lists the events it has not settled, and nothing outside the
# platform acts on a trader opening or abandoning a draft — publishing would put a
# beneficiary name and an amount on a queue for no consumer. Submission is slice 6 and
# has a real audience; it will need one.
CREATE_PAYMENT_REQUEST = CommandNames(
    audit_action="payment_request.created",
    outbox_event_type=None,
    catalogued=True,
)

CANCEL_PAYMENT_REQUEST = CommandNames(
    audit_action="payment_request.cancelled",
    outbox_event_type=None,
    catalogued=True,)

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


# The one action no session can ever perform, because it is what makes sessions
# possible. Every other name here is reached through a request; this one is reached
# through a shell on the host, once, before any staff identity exists.
CREATE_FIRST_ADMIN = CommandNames(
    audit_action="admin_user.bootstrapped",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=(
        "The catalogue's audit actions enumerate what the center does to a trader "
        "and to a role; it has no user-creation action at all, so there is nothing "
        "to align this with rather than a name it contradicts. No outbox event "
        "either: an install-time act has no consumer, and publishing the creation of "
        "the account that will approve every business would put an identity event on "
        "a queue nothing reads. The action is deliberately distinct from any future "
        "`admin_user.created` for the /admin-users route, because the two differ in "
        "the one respect an auditor cares about — that one has an actor and this one "
        "cannot."
    ),
)


# Staff account lifecycle through the API. Deliberately distinct names from
# `CREATE_FIRST_ADMIN`: that one cannot have an actor and these always do, and an auditor
# reading a creation should never have to work out whether a human authorised it.
#
# Outbox events on both, unlike the credential names above. Doc 05's endpoint catalogue
# says role changes, suspension and reactivation create audit **and** outbox events, and a
# staff account appearing or changing is exactly the kind of fact a downstream directory
# or notification consumer would act on. The event types are not catalogued for the same
# reason the trader ones are not — `audit_outbox_catalog.yaml` enumerates financial flows.
CREATE_ADMIN_USER = CommandNames(
    audit_action="admin_user.created",
    outbox_event_type="AdminUserCreated",
    catalogued=False,
    provisional_reason=(
        "The catalogue has no identity-lifecycle action at all, so there is nothing to "
        "align this with rather than a name it contradicts. " + _OUTBOX_GAP
    ),
)

UPDATE_ADMIN_USER = CommandNames(
    audit_action="admin_user.updated",
    outbox_event_type="AdminUserUpdated",
    catalogued=False,
    provisional_reason=(
        "Same catalogue gap. Scoped to contact details: username, status, credential and "
        "role grants each have their own command, because a PATCH that accepted them "
        "would be four commands wearing one name and one audit action. " + _OUTBOX_GAP
    ),
)

# The two state transitions. Separate names from `UPDATE_ADMIN_USER` for the reason that
# module's docstring gives: an amendment and a suspension are different events to
# everybody who reads this trail, and one action string covering both would make
# "who cut this person off" unanswerable without reading the payload of every update.
SUSPEND_ADMIN_USER = CommandNames(
    audit_action="admin_user.suspended",
    outbox_event_type="AdminUserSuspended",
    catalogued=False,
    provisional_reason=(
        "Same identity-lifecycle gap in the catalogue. Doc 05's endpoint table says "
        "suspension creates audit and outbox events, and a staff account losing its "
        "access is exactly what a downstream directory would act on. " + _OUTBOX_GAP
    ),
)

REACTIVATE_ADMIN_USER = CommandNames(
    audit_action="admin_user.reactivated",
    outbox_event_type="AdminUserReactivated",
    catalogued=False,
    provisional_reason=("Same gap, and the counterpart of the suspension. " + _OUTBOX_GAP),
)

# Role permission management. The one command in this family whose *subject* is a role
# rather than a person, and the only one doc 12:642 requires an alert for.
UPDATE_ROLE_PERMISSIONS = CommandNames(
    audit_action="role.permissions_updated",
    outbox_event_type="RolePermissionsUpdated",
    catalogued=False,
    provisional_reason=(
        "audit_outbox_catalog.yaml enumerates financial-flow actions; role administration "
        "is not among them. Named for the permission set rather than for the role, because "
        "the role row itself is untouched and an auditor searching for `role.updated` "
        "would otherwise find nothing when authority changed. " + _OUTBOX_GAP
    ),
)

# The far side of an administrative reset. Deliberately distinct from
# `CHANGE_OWN_PASSWORD`: both are somebody setting their own credential, but this one
# happens without a session, under `AccountAction.RECOVER`, and is the act that ends a
# `recovery_required` state. Merging them would make "did this person recover, or simply
# rotate?" a question answered by joining to another table.
RECOVER_ADMIN_PASSWORD = CommandNames(
    audit_action="credential.recovered",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=(
        "Same catalogue gap as the other credential names. No outbox event: nothing "
        "outside the platform acts on somebody completing a recovery, and publishing it "
        "would put a credential event on a queue for no consumer."
    ),
)


ALL_COMMAND_NAMES: tuple[CommandNames, ...] = (
    RENAME_CENTER_PROFILE,
    REGISTER_TRADER,
    APPROVE_TRADER,
    REJECT_TRADER,
    SUSPEND_TRADER,
    REACTIVATE_TRADER,
    CREATE_BENEFICIARY,
    UPDATE_BENEFICIARY,
    DEACTIVATE_BENEFICIARY,
    CHANGE_OWN_PASSWORD,
    RESET_ADMIN_PASSWORD,
    CREATE_FIRST_ADMIN,
    CREATE_ADMIN_USER,
    UPDATE_ADMIN_USER,
    SUSPEND_ADMIN_USER,
    REACTIVATE_ADMIN_USER,
    UPDATE_ROLE_PERMISSIONS,
    RECOVER_ADMIN_PASSWORD,
    CREATE_PAYMENT_REQUEST,
    CANCEL_PAYMENT_REQUEST,
)
