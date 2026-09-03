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
    # **This said `catalogued=True` and was wrong**, for two milestones, because nothing checked
    # it: `UPLOAD_FILE` was defined in this module and left out of `ALL_COMMAND_NAMES`, the only
    # tuple `tests/backend/test_name_registry_and_errors.py` reads. M6 slice 4 added the missing
    # exports and the claim failed on the next run.
    #
    # The error is a conflation of two catalogues. M4 slice 1 added `file.upload` to
    # **`command_catalog.yaml`** under DOC-CONFLICT-046 — document 05 defines
    # `POST /api/v1/files` and that catalogue had no entry, so the mutation every other upload
    # builds on carried no idempotency or audit contract. `catalogued` on this dataclass means
    # something different: that the **audit action** is in `audit_outbox_catalog.yaml`. It is
    # not. That file's `audit_actions` holds one file name — `file.quarantine_reviewed` at `:65`
    # — and its own `m0_open_items` at `:107` records the file lifecycle as incomplete, so the
    # gap is acknowledged upstream rather than being ours.
    catalogued=False,
    provisional_reason=(
        "`audit_outbox_catalog.yaml` names no upload action — `file.quarantine_reviewed` at "
        "`:65` is its only file entry — and `:107` lists the file lifecycle among its own open "
        "items, so the name may be implemented under `provisional_pending_m0_approval` and must "
        "be renamed to whatever M0 approves. `file.upload` in `command_catalog.yaml` is a "
        "different catalogue answering a different question, and reading it as this one is the "
        "mistake this entry used to make."
    ),
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

# The first command in this aggregate that publishes. Draft creation and cancellation
# carry no outbox event — nothing outside the platform acts on a trader opening or
# abandoning a draft — but submission changes the centre's queue, and
# `05_API_Specification.md:878` requires an event for it. Both names are catalogued:
# `payment_request.submitted` in `audit_actions` and `PaymentRequestSubmitted` in the
# outbox list.
SUBMIT_PAYMENT_REQUEST = CommandNames(
    audit_action="payment_request.submitted",
    outbox_event_type="PaymentRequestSubmitted",
    catalogued=True,
)

CREATE_REVISION = CommandNames(
    audit_action="payment_request.revision_created",
    outbox_event_type=None,
    catalogued=True,
)

CANCEL_PAYMENT_REQUEST = CommandNames(
    audit_action="payment_request.cancelled",
    outbox_event_type=None,
    catalogued=True,
)

# The accountant's three. Every audit action here is catalogued, and the outbox column is
# where they differ — deliberately, not for want of writing three events.
# `audit_outbox_catalog.yaml`'s `outbox_events` lists exactly one accountant event,
# `PaymentRequestCorrectionRequested`, and `command_catalog.yaml` carries
# `outbox_event: null` for start review and mark eligible to match. That is not an
# omission: the same catalogue's open items say the mapping is "every catalogued critical
# command to exactly one audit action and **zero or more** outbox events", so a command
# with no event is anticipated, and another open item asks the owner to decide whether
# event names stay PascalCase or move to a versioned dotted convention. Adding
# `PaymentRequestReviewStarted` here would answer that question on the owner's behalf.
#
# It also happens to be the right shape. A returned request needs the trader told, and
# that is what the event is for. Starting a review and marking eligible change the
# centre's own queue, and M5 has no consumer outside it.
BEGIN_REVIEW = CommandNames(
    audit_action="payment_request.review_started",
    outbox_event_type=None,
    catalogued=True,
)

RETURN_FOR_CORRECTION = CommandNames(
    audit_action="payment_request.correction_requested",
    outbox_event_type="PaymentRequestCorrectionRequested",
    catalogued=True,
)

MARK_ELIGIBLE_FOR_BATCHING = CommandNames(
    audit_action="payment_request.marked_eligible",
    outbox_event_type=None,
    catalogued=True,
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


# --- M6: batching ---------------------------------------------------------------
#
# These four were module-level string literals in `app/commands/payment_batch.py` for two
# slices, which defeats the whole point of this module: the names are
# `provisional_pending_m0_approval` and **will be renamed**, and a literal makes a rename a
# call-site sweep. Nothing caught it, because no gate required a command's audit action to come
# from here — `tests/backend/test_audit_names_come_from_the_registry.py` now does.

CREATE_PAYMENT_BATCH = CommandNames(
    audit_action="payment_batch.created",
    # `command_catalog.yaml:114` says `"outbox_event": null`, and the catalogue is right: at
    # creation nobody outside the platform has anything to act on. `payment_batch_version.created`
    # is a *separate* catalogued action belonging to the separate version-create command, so
    # emitting it here would put a row in the log claiming a command ran that nobody invoked.
    outbox_event_type=None,
    catalogued=True,
)

FINALIZE_PAYMENT_BATCH_VERSION = CommandNames(
    audit_action="payment_batch_version.finalized",
    # The first M6 command that publishes, and the catalogue says so: `command_catalog.yaml:140`
    # names this event because finalization is the moment a manager has something to decide
    # about. Both names are in `audit_outbox_catalog.yaml` — the action at `:28`, the event at
    # `:70`.
    outbox_event_type="PaymentBatchVersionReadyForApproval",
    catalogued=True,
)

CREATE_PAYMENT_BATCH_VERSION = CommandNames(
    audit_action="payment_batch_version.created",
    # `command_catalog.yaml:124` carries `outbox_event: null` for the replacement command. A
    # replacement is not ready for approval — it is a fresh draft — so publishing the
    # ready-for-approval event here would tell a manager to look at something nobody has
    # finalized.
    outbox_event_type=None,
    catalogued=True,
)

APPROVE_PAYMENT_BATCH_VERSION = CommandNames(
    audit_action="payment_batch_version.approved",
    # `command_catalog.yaml:153`. The event is in `audit_outbox_catalog.yaml:72` and the action
    # at `:29`, so neither name is invented here.
    outbox_event_type="PaymentBatchVersionApproved",
    catalogued=True,
)

GENERATE_EXPORT_PREVIEW = CommandNames(
    audit_action="bank_export.preview_generated",
    # `command_catalog.yaml:180` gives this `"outbox_event": null`, and the catalogue is right: a
    # preview is something an accountant looks at, not something any consumer outside the platform
    # can act on. `BankExportSent` is the one event this family owns and it belongs to slice 4's
    # mark-sent, which is the moment a payment genuinely left the building.
    outbox_event_type=None,
    catalogued=True,
)

GENERATE_FINAL_EXPORT = CommandNames(
    audit_action="bank_export.final_generated",
    # `command_catalog.yaml:194` gives this `"outbox_event": null` too. The event this family
    # owns is `BankExportSent`, and it belongs to mark-sent — because generating a file is not
    # the moment a payment leaves the building, and a consumer told otherwise would act early.
    outbox_event_type=None,
    catalogued=True,
)

MARK_EXPORT_SENT = CommandNames(
    audit_action="bank_export.sent_marked",
    # The one event this family owns. `command_catalog.yaml:207` names it and
    # `audit_outbox_catalog.yaml:75` defines it — because a person saying "I uploaded this" is
    # the moment a payment leaves the building, and generating the file was not.
    outbox_event_type="BankExportSent",
    catalogued=True,
)

QUARANTINE_EXPORT_ON_INTEGRITY_FAILURE = CommandNames(
    audit_action="bank_export.integrity_failed",
    # `audit_outbox_catalog.yaml:34` names the action; no event accompanies it.
    #
    # **This name belongs to no command of its own**, and that is deliberate.
    # `permission_catalog.yaml:507` grants `bank_export.quarantine` to `default_roles: []` — to
    # nobody — and `command_catalog.yaml` has no row for it, so a manual quarantine is a
    # capability nothing can invoke. §15.5 describes quarantine as what *happens* when a check
    # fails, and this action is written by the code that runs the checks. G-4 records the
    # unreachable permission; slice 5A took the same reading for invalidation after the plan had
    # said otherwise.
    outbox_event_type=None,
    catalogued=True,
)

INVALIDATE_BATCH_APPROVAL = CommandNames(
    audit_action="payment_batch_approval.invalidated",
    # `audit_outbox_catalog.yaml:31` names the action and its `outbox_events` list names nothing
    # for it. That is consistent: an invalidation is the *inside* of a replacement, which already
    # publishes nothing, so there is no moment here that a consumer outside the platform could
    # act on. An invented `PaymentBatchApprovalInvalidated` would be an event type no consumer
    # contract names.
    #
    # **This name belongs to no command of its own.** It is written by
    # `create_replacement_version`, because `05_API_Specification.md` defines no invalidation
    # endpoint and `:1366` makes the replacement the thing that invalidates. The M7 plan
    # originally said otherwise and slice 5A corrected it — a command here would have been a
    # route no document defines, for a permission that authorises nothing.
    outbox_event_type=None,
    catalogued=True,
)

REJECT_PAYMENT_BATCH_VERSION = CommandNames(
    audit_action="payment_batch_version.rejected",
    # `command_catalog.yaml:166` gives this one `"outbox_event": null`, and
    # `audit_outbox_catalog.yaml` defines no rejection event either. That asymmetry is the
    # catalogue's answer, not an omission to be helpfully corrected: an approval releases work
    # to the export side and something downstream must hear it, while a rejection returns the
    # batch to the accountant who is already looking at it. Publishing an invented
    # `PaymentBatchVersionRejected` would put an event type in the outbox that no consumer
    # contract names — the same shape as an audit action nothing catalogues. AUD-APPROVAL-001
    # asserts this absence rather than leaving it to be read as forgetfulness.
    outbox_event_type=None,
    catalogued=True,
)

# G-8, answered without inventing a name. The plan offered two options: catalogue a supersession
# action, or let the replacement's own creation action carry the record. The second needs no
# invention and is what `CREATE_PAYMENT_BATCH_VERSION` above does — the audit row for the
# replacement names the version it superseded in its `previous_values`, so "which version did
# this replace" is answerable from one row rather than from two that must be correlated.
#
# The first option stays open for the owner: if M0 catalogues
# `payment_batch_version.superseded`, this comment is where the decision lands.

# There is deliberately **no** release entry. A `RELEASE_ATTEMPT_ALLOCATION` name was written and
# removed in the same slice: `05_API_Specification.md` defines no release endpoint,
# `permission_catalog.yaml` no permission, and `§17` says clients do not manipulate attempts
# directly — so a standalone release command would have had no caller, and its name no writer.
#
# Release is audited by the command that causes it. `create_replacement_version` and
# `cancel_batch` each record `released_allocations` in their own audit row, and every allocation
# row carries `released_at` and `release_reason`. That satisfies
# `FINANCIAL_INTEGRITY_BASELINE.md:41-43`, which names release's *occasions* rather than treating
# it as a command.

CANCEL_PAYMENT_BATCH = CommandNames(
    audit_action="payment_batch.cancelled",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=(
        "`audit_outbox_catalog.yaml` catalogues `payment_request.cancelled` at `:25` and no "
        "cancellation action for the batch aggregate at all — an asymmetry rather than a "
        "decision, and the catalogue's own `m0_open_items` records that its event set is "
        "incomplete. Cancelling a batch is a governed financial state change and cannot go "
        "unaudited, so the name follows the aggregate's existing dotted convention and must be "
        "renamed to whatever M0 approves. No outbox event: nothing outside the platform acts on "
        "an accountant abandoning a draft, which is the same reasoning "
        "`CANCEL_PAYMENT_REQUEST` applies one aggregate down. G-5 widened the command to the "
        "ready-for-approval and approved origins §29.2 also permits and that conclusion still "
        "holds — cancelling an approved batch refuses outright once a final export is marked "
        "sent, so no cancellation can reach a state anything outside the platform acted on."
    ),
)

# --- M4: bank configuration -----------------------------------------------------
#
# Four names that were literals at their call sites in `app/commands/bank_configuration.py`
# until M6 slice 4's registry gate found them. All four are in the approved catalogue, so
# nothing about the names changes — what changes is that a rename is now one edit here rather
# than four call-site edits in a module nobody is currently reading.
#
# None publishes. `audit_outbox_catalog.yaml`'s `outbox_events` has no bank-configuration event,
# and `05_API_Specification.md` asks for none: activating a bank profile version changes what the
# centre will send *next*, and nothing outside the platform acts on it until an export exists.

CREATE_BANK_PROFILE_VERSION = CommandNames(
    audit_action="bank_profile.version_created",
    outbox_event_type=None,
    catalogued=True,
)

ACTIVATE_BANK_PROFILE_VERSION = CommandNames(
    audit_action="bank_profile.version_activated",
    outbox_event_type=None,
    catalogued=True,
)

CREATE_BANK_MAPPING_VERSION = CommandNames(
    audit_action="bank_mapping.version_created",
    outbox_event_type=None,
    catalogued=True,
)

CREATE_SOURCE_BANK_ACCOUNT = CommandNames(
    audit_action="source_bank_account.created",
    outbox_event_type=None,
    catalogued=True,
)

UPLOAD_BANK_RESULT_BUNDLE = CommandNames(
    audit_action="bank_result_bundle.uploaded",
    outbox_event_type=None,
    # `audit_outbox_catalog.yaml:36` names the action and `command_catalog.yaml:264` gives the
    # command its permission, idempotency and audit contract. Nothing outside the platform acts on
    # a bundle arriving, so no outbox event: the centre's own queue changes, and M9's confirmation
    # is the point at which anything downstream cares.
    catalogued=True,
)

LINK_BANK_RESULT_BUNDLE_TO_BATCH = CommandNames(
    audit_action="bank_result_bundle.linked_to_batch",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=(
        "Third instance of DOC-CONFLICT-052's shape. `bank_result_bundle.link_batch` is in the "
        "approved permission catalogue at permission_catalog.yaml:528 and is seeded to accountant "
        "by 20260801_0008_seed_rbac_catalogue.py:143,208 — and it has no row in "
        "command_catalog.yaml and no entry in audit_outbox_catalog.yaml, whose only two bundle "
        "actions are bank_result_bundle.uploaded and .closed. So an approved, seeded permission "
        "authorises a command no catalogue describes, exactly as -052 recorded for "
        "payment_batch.cancel_draft and payment_batch_version.invalidate_approval. M8 slice 1 "
        "implements the route against the permission's own identifier, which is what M6 slice 4 "
        "did under that conflict, and this action name must be renamed to whatever M0 approves. "
        "The catalogue is provisional_pending_m0_approval and its own m0_open_items records its "
        "event set as incomplete, so the gap is acknowledged upstream rather than invented here."
    ),
)

CLOSE_BANK_RESULT_BUNDLE = CommandNames(
    audit_action="bank_result_bundle.closed",
    outbox_event_type=None,
    # `audit_outbox_catalog.yaml:37` and `command_catalog.yaml:593`.
    catalogued=True,
)

ATTACH_EXTERNAL_EVIDENCE = CommandNames(
    audit_action="receipt_segment.external_attached",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=(
        "Fourth instance of DOC-CONFLICT-052's shape, and the narrowest yet. "
        "`receipt_segment.create_external` is in the approved permission catalogue at "
        "permission_catalog.yaml:534 and seeded to accountant; command_catalog.yaml has a row for "
        "receipt_segment.create_crop at :277 and none for the external method, and "
        "audit_outbox_catalog.yaml names receipt_segment.crop_created at :38 and no external "
        "counterpart. So the two creation methods 04_Database_Schema.md:1259 both marks Phase 1A "
        "are catalogued asymmetrically: the one that needs a PDF renderer is described and the one "
        "that needs nothing is not. M8 slice 2 implements the route against the permission's own "
        "identifier, as M6 slice 4 did under this conflict, and this action name must be renamed "
        "to whatever M0 approves. No outbox event: nothing outside the platform acts on evidence "
        "arriving, and M9's confirmation is where anything downstream begins to care."
    ),
)

CREATE_RECEIPT_CROP = CommandNames(
    audit_action="receipt_segment.crop_created",
    # `audit_outbox_catalog.yaml:38` names the action and gives it no event, which is right: nothing
    # outside the platform acts on evidence being cut out of a page. M9's confirmation is where
    # anything downstream begins to care.
    outbox_event_type=None,
    # **True — and the only M8 command for which it is.** `permission_catalog.yaml:537` approves and
    # seeds `receipt_segment.create_crop`; `command_catalog.yaml:277` carries the row with this
    # exact path, `idempotency: required`, and preconditions naming the normalized rectangle, page,
    # rotation, renderer version and derived checksum; `audit_outbox_catalog.yaml:38` names the
    # audit action. Nothing here is provisional.
    #
    # Read against slices 1, 2 and 3, this is what makes Q-12 precise rather than a complaint. The
    # catalogues are not vaguely incomplete for the evidence path — they describe in full the one
    # command that needs a PDF renderer, and omit `link_batch`, `create_external` and the entire
    # review queue. That asymmetry is the finding, and it is worth reporting as an asymmetry.
    catalogued=True,
)

# M8 slice 3. Five names for the review queue, and the fifth instance of DOC-CONFLICT-052's shape —
# the broadest one yet, so the reason is written once here and the four below refer to it.
#
# `permission_catalog.yaml:640,646,652` approves `manual_review.read`, `.assign` and `.resolve`, all
# seeded. `command_catalog.yaml` has **no row for any of them**, and `audit_outbox_catalog.yaml` has
# **no manual-review action at all**, while `05_API_Specification.md:2058` defines six routes. So an
# entire operator-facing surface is approved at the permission layer and undescribed at the command
# layer.
#
# Read with `link_batch` (slice 1) and `create_external` (slice 2), the pattern is no longer
# incidental: `command_catalog.yaml` is systematically incomplete for the evidence path, and
# `audit_outbox_catalog.yaml`'s own `m0_open_items` says its event set is incomplete. M8 needs one
# catalogue update, not five separate rows — recorded as Q-12 in the plan. Every name below must be
# renamed to whatever M0 approves.
_REVIEW_QUEUE_REASON = (
    "M8 slice 3. Fifth instance of DOC-CONFLICT-052: permission_catalog.yaml:640,646,652 approve "
    "and seed manual_review.read/.assign/.resolve, command_catalog.yaml has no row for any of "
    "them, and audit_outbox_catalog.yaml names no manual-review action at all — while "
    "05_API_Specification.md:2058 defines six routes. Implemented against the permissions' own "
    "identifiers, as M6 slice 4 did under this conflict. Q-12 asks for one catalogue update for "
    "the whole evidence path rather than five rows; until then this name is provisional and must "
    "be renamed to whatever M0 approves. No outbox event: a queue item is internal work, and "
    "nothing outside the platform acts on somebody being asked to look at something."
)

OPEN_REVIEW_TASK = CommandNames(
    audit_action="manual_review_task.opened",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_REVIEW_QUEUE_REASON,
)

ASSIGN_REVIEW_TASK = CommandNames(
    audit_action="manual_review_task.assigned",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_REVIEW_QUEUE_REASON,
)

START_REVIEW_TASK = CommandNames(
    audit_action="manual_review_task.started",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_REVIEW_QUEUE_REASON,
)

RESOLVE_REVIEW_TASK = CommandNames(
    audit_action="manual_review_task.resolved",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_REVIEW_QUEUE_REASON,
)

CANCEL_REVIEW_TASK = CommandNames(
    audit_action="manual_review_task.cancelled",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_REVIEW_QUEUE_REASON,
)
# --- M9 slice 1: matching candidates -------------------------------------------
#
# **A correction to the M9 plan's own headline.** The plan says the milestone's governance is
# complete before its code, and for acceptance that is exactly true — `command_catalog.yaml:290`
# carries the row with this path, `idempotency: required`, both "does not confirm" preconditions,
# and `audit_outbox_catalog.yaml:39` names the action. It is the first M9 command and it needs
# nothing invented.
#
# **Creation and rejection are not.** `permission_catalog.yaml` approves and seeds
# `matching_candidate.create` and `.review`; `command_catalog.yaml` has a row for neither, and
# `audit_outbox_catalog.yaml` names no candidate action but the accepted one — while
# `05_API_Specification.md:1798` and `:1816` define both routes. That is DOC-CONFLICT-052's shape
# for the sixth time, and the plan's claim was too broad: it listed "candidate acceptance" among
# the catalogued rows accurately and then generalised from it.
_CANDIDATE_DECISION_REASON = (
    "M9 slice 1. Sixth instance of DOC-CONFLICT-052: permission_catalog.yaml approves and seeds "
    "matching_candidate.create and matching_candidate.review, 05_API_Specification.md:1798 and "
    ":1816 define the two routes, and neither command_catalog.yaml nor audit_outbox_catalog.yaml "
    "names either command — while the acceptance sitting between them is catalogued completely. "
    "Implemented against the permissions' own identifiers, the precedent M6 slice 4 and M8 slice "
    "3 set under this conflict. The names follow the aggregate's catalogued spelling "
    "(matching_candidate.accepted_for_confirmation) and must be renamed to whatever M0 approves. "
    "No outbox event: a suggestion being made or refused is internal work, and nothing outside "
    "the platform can act on it — 04_Database_Schema.md:1274 is explicit that a candidate decides "
    "no financial fact."
)

CREATE_MATCHING_CANDIDATE = CommandNames(
    audit_action="matching_candidate.proposed",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_CANDIDATE_DECISION_REASON,
)

ACCEPT_MATCHING_CANDIDATE = CommandNames(
    audit_action="matching_candidate.accepted_for_confirmation",
    # `audit_outbox_catalog.yaml:39` names the action; `command_catalog.yaml:298` gives it
    # `outbox_event: null` in as many words. Right, and for the reason §12.5 gives: acceptance
    # opens a context for confirmation and settles nothing a consumer could act on.
    outbox_event_type=None,
    # **True.** Permission, command row and audit action all approved, with the row's own
    # preconditions naming the two things this command must not do.
    catalogued=True,
)

REJECT_MATCHING_CANDIDATE = CommandNames(
    audit_action="matching_candidate.rejected",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_CANDIDATE_DECISION_REASON,
)

# --- M9 slice 2: confirmed evidence links --------------------------------------
#
# **All three are catalogued, and this is the first slice in the project where that is true of
# every command in it.** `audit_outbox_catalog.yaml:40-42` names the three actions, `:76` names the
# one outbox event, `command_catalog.yaml` carries a row for each with its permission, idempotency
# and concurrency rule, and `20260801_0008:218-220` seeds all three permissions to `accountant`.
# Nothing here is provisional — which is what the M9 plan claimed of the whole milestone and turns
# out to be true of this slice rather than of slice 1.

CONFIRM_EVIDENCE_LINK = CommandNames(
    audit_action="evidence_link.confirmed",
    # `command_catalog.yaml` gives it `outbox_event: null`. Right: confirming evidence settles what
    # a segment *means*, and nothing outside the platform acts on that until a result is published.
    outbox_event_type=None,
    catalogued=True,
)

REPLACE_EVIDENCE_LINK = CommandNames(
    audit_action="evidence_link.replaced",
    # **The only M9 command so far with an outbox event**, and the asymmetry is the point.
    # `05_API_Specification.md:1854`: when a published result materially changes, a corrected
    # publication and a trader notification are required. Replacement is where evidence stops
    # agreeing with what a trader was shown, so it is the one a consumer must hear about.
    outbox_event_type="EvidenceLinkReplaced",
    catalogued=True,
)

REVOKE_EVIDENCE_LINK = CommandNames(
    audit_action="evidence_link.revoked",
    outbox_event_type=None,
    # Catalogued — **and its command row carries
    # `status: blocked_by_voided_vs_revoked_status_conflict`**, the catalogue flagging the
    # `revoked`/`voided` disagreement between documents 06/08 and 04/05 before anybody wrote code
    # against it. The audit action itself is not in doubt: `audit_outbox_catalog.yaml:42` spells it
    # `revoked`, the canonical side. `20260830_0029`'s docstring records how the stored status and
    # the route path were settled.
    catalogued=True,
)

# --- M9 slice 3: payment results -----------------------------------------------
#
# Both actions are in `audit_outbox_catalog.yaml:43-44` and both events at `:74-75`. **Both
# command rows are marked blocked**, and the blockers are resolved rather than inherited:
# `confirm_paid` carries `blocked_by_result_persistence_and_evidence_policy` and `confirm_failed`
# `blocked_by_result_persistence_contract`.
#
# *Result persistence* was M6 creating the six result columns on `payment_attempts` and granting
# the runtime nothing on them — `20260830_0030` is that half, column by column, with every
# snapshot still unwritable. *Evidence policy* is the plan's G-3: doc 05 `:1580` makes a reason
# required "by policy" when no evidence exists and no approved document states the policy, so the
# reason is required in every evidence-free case and the owner still owes the decision on whether
# such a confirmation needs a second person.

CONFIRM_ATTEMPT_PAID = CommandNames(
    audit_action="payment_attempt.paid_confirmed",
    # `:74`. The first outbox event in M9 that something outside the platform genuinely acts on:
    # a paid attempt is what a publication is eventually built from.
    outbox_event_type="PaymentAttemptPaid",
    catalogued=True,
)

CONFIRM_ATTEMPT_FAILED = CommandNames(
    audit_action="payment_attempt.failed_confirmed",
    outbox_event_type="PaymentAttemptFailed",
    catalogued=True,
)

# --- M9 slice 3B: retry ---------------------------------------------------------
#
# **The slice the plan forgot.** §17 `:1121` lists five payment-result commands and the M9 plan
# named three of them; these two were built after re-reading that list at the top of slice 3.

CREATE_RETRY_ATTEMPT = CommandNames(
    audit_action="payment_attempt.retry_created",
    # `audit_outbox_catalog.yaml:45` names the action and `command_catalog.yaml` gives the command
    # `outbox_event: null`. Right: a retry that has not been batched, exported or sent is a plan,
    # and nothing outside the platform can act on a plan.
    outbox_event_type=None,
    catalogued=True,
)

MARK_RETRY_REQUIRED = CommandNames(
    audit_action="payment_attempt.retry_required",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=(
        "M9 slice 3B. `05_API_Specification.md:1608` defines "
        "POST /payment-attempts/{attempt_id}/mark-retry-required and `command_catalog.yaml` has "
        "no row for it, while `audit_outbox_catalog.yaml` names retry_created and no separate "
        "action for the decision that precedes it. Seventh instance of DOC-CONFLICT-052. "
        "Implemented against `payment_attempt.create_retry`, the nearest approved permission — "
        "deciding that a retry is needed is the same authority as making one, and the catalogue "
        "has no `mark_retry_required` to borrow instead. The name follows the aggregate's "
        "catalogued spelling and must be renamed to whatever M0 approves. No outbox event: "
        "§17.4 says in as many words that this creates and sends nothing."
    ),
)


# --- M9 slice 5: publication ----------------------------------------------------
#
# **Fully catalogued, and it is the first M9 slice that is.** `audit_outbox_catalog.yaml:46` names
# the action, `:77` the event, `command_catalog.yaml`'s `payment_publication.publish` row names
# both together, and `20260801_0008` already seeded the permission to the accountant role. Nothing
# to declare and nothing to reconcile — worth saying out loud after three slices that each opened
# with a conflict.
#
# The preview has no entry, deliberately. It creates no publication and doc 05 §20.1 says so; what
# it does write is the request's own status, which `payment_request.*` already covers.

PUBLISH_PAYMENT_RESULT = CommandNames(
    audit_action="payment_publication.created",
    # `:77`. A trader has to be told, and `notifications` (M9 slice 7, the plan's G-2) is the
    # consumer this event is waiting for.
    outbox_event_type="PaymentResultPublicationCreated",
    catalogued=True,
)


# --- M9 slice 6: the trader responds -------------------------------------------
#
# `audit_outbox_catalog.yaml:48-49` names both actions and lists **no outbox event for either**,
# which is right and worth saying out loud: nothing outside this platform acts on a trader's
# opinion of a result. A dispute's consumer is a person, and the review task is how they hear
# about it — an event would be a second delivery path for the same fact, and the one nobody reads.

ACKNOWLEDGE_PUBLICATION = CommandNames(
    audit_action="payment_publication.acknowledged",
    outbox_event_type=None,
    catalogued=True,
)

DISPUTE_PUBLICATION = CommandNames(
    audit_action="payment_publication.disputed",
    outbox_event_type=None,
    catalogued=True,
)


# --- M9 slice 7B: correction ----------------------------------------------------
#
# `audit_outbox_catalog.yaml:47` names the action and `:78` the event, and `command_catalog.yaml`'s
# `payment_publication.correct_paid_result` row pairs them. That row also carries
# `status: blocked_by_business_policy_and_api_persistence_contract` — and the business policy half
# is **no longer blocked**: ADR_INDEX's POL-002 is approved for Phase 1A and says manager authority
# or dual control is required, with the accountant-only default rejected. The API persistence half
# is still open, which is why this command is reached through document 05's existing replacement
# address rather than the `path: TBD` the catalogue records.

CORRECT_PAYMENT_PUBLICATION = CommandNames(
    audit_action="payment_publication.superseded",
    # `:78`. The event slice 7's projection turns into the trader notification §17.7's seventh step
    # requires — which is why that slice had to come first.
    outbox_event_type="TraderResultCorrected",
    catalogued=True,
)


# --- M10 slice 1: the gold sale order ------------------------------------------
#
# **None of these three is catalogued, and the M10 plan predicted it.**
# `audit_outbox_catalog.yaml` names `gold_sale.dispatched` and `incoming_payment.confirmed` for the
# whole milestone — two actions against §18 `:1212`'s twelve capabilities. G-3 records that ten
# capabilities have no catalogued action and that M10 is shaped like M8, which shipped seven
# declarations, rather than like M9, which shipped one.
#
# So these are declared rather than invented: each names the approved permission its route already
# uses, and each is an instance of DOC-CONFLICT-052. M0 owes the names.

_GOLD_SALE_REASON = (
    "M10 slice 1. `audit_outbox_catalog.yaml` names only `gold_sale.dispatched` and "
    "`incoming_payment.confirmed` for this milestone, and nothing for creating, submitting or "
    "pricing an order — the M10 plan's G-3, which counted ten of twelve capabilities with no "
    "catalogued action before any code was written. Implemented against {permission}, the "
    "approved permission the route already requires. The name follows the aggregate's catalogued "
    "spelling and must be renamed to whatever M0 approves."
)

CREATE_GOLD_SALE_ORDER = CommandNames(
    audit_action="gold_sale.created",
    # No outbox event. A draft order nobody has submitted is a form somebody is filling in, and
    # nothing outside the platform can act on one.
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_GOLD_SALE_REASON.format(permission="`gold_sale.create_own`"),
)

SUBMIT_GOLD_SALE_ORDER = CommandNames(
    audit_action="gold_sale.submitted",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_GOLD_SALE_REASON.format(permission="`gold_sale.review`"),
)

PRICE_GOLD_SALE_ORDER = CommandNames(
    audit_action="gold_sale.priced",
    # Also none, and this one is worth stating: a price is what the *trader* must be told, and
    # M9 slice 7's `notifications` is the mechanism for telling them. That is slice 8's wiring,
    # not an event invented here — `audit_outbox_catalog.yaml` lists no gold-sale event at all.
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_GOLD_SALE_REASON.format(permission="`gold_sale.price`"),
)


# --- M10 slice 2: the trader's claim ------------------------------------------
#
# The fourth uncatalogued name in two slices, and the plan's G-3 said to expect it.
# `audit_outbox_catalog.yaml` names `incoming_payment.confirmed` — the *confirmation*, which is
# slice 6 — and nothing for the claim that precedes it. That gap is the milestone's whole shape in
# miniature: the catalogue names the moments money is decided and not the moments it is claimed.

SUBMIT_INCOMING_RECEIPT = CommandNames(
    audit_action="incoming_receipt.submitted",
    # No outbox event. Doc 05 §21.3: "Uploading evidence never confirms payment", so nothing
    # outside the platform can act on a claim — and the catalogue lists no gold-sale event at all.
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=(
        "M10 slice 2. `05_API_Specification.md:1981` defines "
        "POST /gold-sale-orders/{order_id}/incoming-payment-receipts and "
        "`audit_outbox_catalog.yaml` has no action for it — it names "
        "`incoming_payment.confirmed`, which is slice 6's confirmation against a bank statement, "
        "and nothing for the claim that precedes it. Implemented against "
        "`incoming_receipt.create_own`, the approved permission the route requires and the one "
        "`20260801_0008:377` gives the trader. The name follows the aggregate's catalogued "
        "spelling and must be renamed to whatever M0 approves."
    ),
)


# --- M10 slice 3: the statement the centre imports itself ---------------------
#
# **The first M10 slice whose main action is catalogued, and the plan predicted the opposite.** Its
# governance survey reported two M10 audit actions; `audit_outbox_catalog.yaml` carries four, and
# two of those are this slice's aggregate — `bank_statement.import_run_created` and
# `bank_statement.import_run_confirmed`. The survey had searched for table names where the
# catalogue names business objects. The plan is corrected; this comment is here so the next reader
# does not re-derive it from an empty grep.
#
# The upload is the exception, and a narrow one: `command_catalog.yaml` has a row for
# `bank_statement.create_import_run` and none for `POST /api/v1/bank-statements`, so the file a run
# parses arrives through a route with no catalogued name.

CREATE_BANK_STATEMENT_FILE = CommandNames(
    audit_action="bank_statement.uploaded",
    # No outbox event. An uploaded statement nobody has parsed is a file on disk; the parse is what
    # produces facts, and the catalogue gives even the two catalogued run actions
    # `outbox_event: null`.
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=(
        "M10 slice 3. `05_API_Specification.md:1990` defines POST /api/v1/bank-statements and "
        "`audit_outbox_catalog.yaml` has no action for it, while carrying two for the import runs "
        "that follow — `bank_statement.import_run_created` and "
        "`bank_statement.import_run_confirmed`. So the catalogue names what is done to a statement "
        "file and not the arrival of the file itself. Implemented against "
        "`bank_statement.upload`, the approved permission the route requires. The name follows the "
        "catalogued `bank_statement.` prefix and must be renamed to whatever M0 approves."
    ),
)

DISPATCH_GOLD_SALE = CommandNames(
    # `audit_outbox_catalog.yaml:51`. **The third fully catalogued M10 command**, and the one this
    # milestone was built toward: M0 named the two moments money is decided and the one moment gold
    # moves, which is exactly the set an auditor would ask for.
    audit_action="gold_sale.dispatched",
    # `command_catalog.yaml`'s `gold_sale.dispatch` gives `outbox_event: null`, right for the same
    # reason slice 6's is: a trader learning their gold has been dispatched is a notification, and
    # M9 slice 7's projection is the mechanism for one.
    outbox_event_type=None,
    catalogued=True,
)

CONFIRM_INCOMING_PAYMENT = CommandNames(
    # `audit_outbox_catalog.yaml:50`, and `command_catalog.yaml`'s `incoming_payment.confirm` names
    # the same action against the same route. **The second fully catalogued M10 command**, after
    # slice 3's import run — and the milestone's most important moment is one of the two the
    # catalogue anticipated, which is not a coincidence: M0 named the places money is decided.
    audit_action="incoming_payment.confirmed",
    # `outbox_event: null` in that command row. A trader learning their payment was accepted is a
    # notification, and M9 slice 7's projection is the mechanism — slice 8's wiring, not an event
    # invented here.
    outbox_event_type=None,
    catalogued=True,
)

_MATCH_REASON = (
    "M10 slice 5. `05_API_Specification.md:2002` defines "
    "POST /incoming-payment-receipts/{receipt_id}/matches and `audit_outbox_catalog.yaml` has no "
    "action for it — it names `incoming_payment.confirmed`, which is slice 6, and nothing for the "
    "suggestion that precedes it. The same gap as the claim in slice 2, one step further along: "
    "the catalogue names the moments money is decided and not the moments it is proposed. "
    "Implemented against `incoming_payment.match`, the approved permission the route requires. "
    "The name follows the aggregate's catalogued spelling and must be renamed to whatever M0 "
    "approves."
)

PROPOSE_INCOMING_MATCH = CommandNames(
    audit_action="incoming_match.proposed",
    # No outbox event. A suggestion nobody has agreed with is not a fact about money, and §21.5
    # keeps candidate acceptance and financial confirmation separate — an event here would let
    # something outside the platform act on the first as though it were the second.
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_MATCH_REASON,
)

REJECT_INCOMING_MATCH = CommandNames(
    audit_action="incoming_match.rejected",
    outbox_event_type=None,
    catalogued=False,
    provisional_reason=_MATCH_REASON,
)

CREATE_STATEMENT_IMPORT_RUN = CommandNames(
    # `audit_outbox_catalog.yaml:57`, and `command_catalog.yaml`'s
    # `bank_statement.create_import_run` names the same action against the same route. Nothing is
    # declared here — the first M10 command for which that is true.
    audit_action="bank_statement.import_run_created",
    # `outbox_event: null` in that command row, and it is right: a queued parse has produced no
    # rows, so there is no fact for anything outside the platform to act on. Doc 08 §8.2's
    # confirmation, which makes rows available for matching, is not this slice.
    outbox_event_type=None,
    catalogued=True,
)


# Every `CommandNames` defined above, and the gate that reads this tuple is the only thing
# checking any of them against the catalogue. Three M5 entries — `BEGIN_REVIEW`,
# `RETURN_FOR_CORRECTION` and `MARK_ELIGIBLE_FOR_BATCHING` — were defined and **left out of this
# tuple**, so `test_name_registry_and_errors.py` never saw them: a gate whose input was
# incomplete, which is the same shape as a mechanism with no caller.
# `test_audit_names_come_from_the_registry.py` now fails if a definition is missing from here.
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
    CREATE_REVISION,
    SUBMIT_PAYMENT_REQUEST,
    BEGIN_REVIEW,
    RETURN_FOR_CORRECTION,
    MARK_ELIGIBLE_FOR_BATCHING,
    CREATE_PAYMENT_BATCH,
    FINALIZE_PAYMENT_BATCH_VERSION,
    CREATE_PAYMENT_BATCH_VERSION,
    CANCEL_PAYMENT_BATCH,
    CREATE_BANK_PROFILE_VERSION,
    ACTIVATE_BANK_PROFILE_VERSION,
    CREATE_BANK_MAPPING_VERSION,
    CREATE_SOURCE_BANK_ACCOUNT,
    # M8 slice 1. Added here in the same edit that defines them, which is the whole lesson of the
    # two comments below.
    UPLOAD_BANK_RESULT_BUNDLE,
    LINK_BANK_RESULT_BUNDLE_TO_BATCH,
    CLOSE_BANK_RESULT_BUNDLE,
    # M8 slice 2, added in the same edit that defines it.
    ATTACH_EXTERNAL_EVIDENCE,
    # M8 slice 4, likewise. The only M8 name that is fully catalogued.
    CREATE_RECEIPT_CROP,
    # M8 slice 3, likewise added in the edit that defines them.
    OPEN_REVIEW_TASK,
    ASSIGN_REVIEW_TASK,
    START_REVIEW_TASK,
    RESOLVE_REVIEW_TASK,
    CANCEL_REVIEW_TASK,
    # M4's file lifecycle. Defined since M4 and **left out of this tuple**, so their catalogue
    # position went unverified for two milestones — the same gap as M5's accountant three, found
    # by the same gate on the same run.
    UPLOAD_FILE,
    REQUEST_FILE_PREVIEW,
    # M7 slice 1. Added in the same commit as the entries themselves, which is the whole lesson
    # of the two gaps above: this tuple is the only thing
    # `tests/backend/test_name_registry_and_errors.py` iterates, so a name defined and left out
    # of it is a name whose catalogue position nobody checks — and the gate stays green while it
    # goes unchecked.
    APPROVE_PAYMENT_BATCH_VERSION,
    REJECT_PAYMENT_BATCH_VERSION,
    # M7 slice 5A. In the tuple in the same commit as the entry, for the reason above it.
    INVALIDATE_BATCH_APPROVAL,
    # M7 slice 2, same commit as its entry, same reason.
    GENERATE_EXPORT_PREVIEW,
    # M7 slice 3.
    GENERATE_FINAL_EXPORT,
    QUARANTINE_EXPORT_ON_INTEGRITY_FAILURE,
    # M7 slice 4.
    MARK_EXPORT_SENT,
    # M9 slice 1, in the tuple in the same commit as the entries. Only the middle one is
    # catalogued, which is the finding the entries above record.
    CREATE_MATCHING_CANDIDATE,
    ACCEPT_MATCHING_CANDIDATE,
    REJECT_MATCHING_CANDIDATE,
    # M9 slice 2, same commit as the entries. All three catalogued.
    CONFIRM_EVIDENCE_LINK,
    REPLACE_EVIDENCE_LINK,
    REVOKE_EVIDENCE_LINK,
    # M9 slice 3, likewise. Both catalogued, both command rows previously blocked.
    CONFIRM_ATTEMPT_PAID,
    CONFIRM_ATTEMPT_FAILED,
    # M9 slice 3B. One catalogued, one not — the decision that precedes a retry has a route and
    # no command row.
    CREATE_RETRY_ATTEMPT,
    MARK_RETRY_REQUIRED,
    # M9 slice 5, same commit as its entry. Catalogued on both sides.
    PUBLISH_PAYMENT_RESULT,
    # M9 slice 6. Both catalogued, neither with an event.
    ACKNOWLEDGE_PUBLICATION,
    DISPUTE_PUBLICATION,
    # M9 slice 7B. Catalogued on both sides; its command row's business-policy blocker is what
    # POL-002 answered.
    CORRECT_PAYMENT_PUBLICATION,
    # M10 slice 1, same commit as the entries. **None catalogued** — the first block of that kind
    # since M8, and the M10 plan's G-3 says why in advance.
    CREATE_GOLD_SALE_ORDER,
    SUBMIT_GOLD_SALE_ORDER,
    PRICE_GOLD_SALE_ORDER,
    # M10 slice 2. Also uncatalogued: the catalogue names the confirmation, not the claim.
    SUBMIT_INCOMING_RECEIPT,
    # M10 slice 3. The second is fully catalogued — the first M10 name that is — and the first is
    # not, because the catalogue names what happens to a statement file and not its arrival.
    CREATE_BANK_STATEMENT_FILE,
    CREATE_STATEMENT_IMPORT_RUN,
    # M10 slice 5. Uncatalogued, one step past slice 2's gap: the catalogue names the confirmation
    # and not the suggestion that precedes it.
    PROPOSE_INCOMING_MATCH,
    REJECT_INCOMING_MATCH,
    # M10 slice 6, and fully catalogued — the second M10 name that is.
    CONFIRM_INCOMING_PAYMENT,
    # M10 slice 7, the third and last catalogued one: the moment gold moves.
    DISPATCH_GOLD_SALE,
)
