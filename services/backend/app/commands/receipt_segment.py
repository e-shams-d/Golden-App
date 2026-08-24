"""Evidence that needs no renderer. `05_API_Specification.md` §19.1.

M8 slice 2. **One command, where the plan expected two**, and the missing one is the finding.

**`attach_external` is the creation method that renders nothing.** §12.4 at `:1249` names five;
this builds `manual_external_attachment`, which takes an already-uploaded file as evidence whole.
It needs no PDF library, which is why slice 2 could be written while Q-4 is open — and it is not a
placeholder for the crop: `15_Agent_Implementation_Plan.md:1077` requires the external-evidence
fallback to stay available, so a bundle nothing can render is still workable through this path.

**There is no field-correction command, because the permission catalogue already refused one.**
The plan's slice 2 expected a guarded `PATCH` per `05_API_Specification.md:1792`, with the
finalization rule at `:1795`. `permission_catalog.yaml` settles it in the other direction and says
so explicitly:

    receipt_segment.update:
      status: unresolved_no_exact_canonical_target
      canonical_targets: []
      resolution: deny until an explicitly scoped pre-finalization update permission is approved

and its `m0_open_items` carries `receipt_segment_update_permission` with
`conservative_effect: deny_update_until_action-specific_permission_is_approved`, citing
`:1788-1795` — the same lines the plan read. So this is **not** a gap discovered here, like Q-6 and
Q-7 were; it is an approved conservative decision that the plan did not consult. Shipping the route
would have violated a rule M0 has already taken, which is worse than any of the three gaps slice 1
worked around.

A `correct_fields` function was written and deleted rather than left unexposed. A command with no
caller is the defect this repository has produced in every milestone, and one whose route is
forbidden by governance would be the most misleading version of it — reviewed, tested, green, and
unreachable by design. Q-9 records what the owner has to approve before it exists.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.audit.redaction import RedactionPolicy
from app.audit.registry import ATTACH_EXTERNAL_EVIDENCE
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.commands.bank_result_bundle import recount
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.models.bank_result_bundle import BUNDLE_CLOSED, BankResultBundle, BankResultBundleFile
from app.db.models.file_object import CLEAN_SCAN_STATUS, FileObject
from app.db.models.receipt_segment import METHOD_EXTERNAL, SEGMENT_CREATED, ReceiptSegment
from app.db.unit_of_work import SqlAlchemyUnitOfWork

METADATA_SCHEMA = "audit.receipt_segment"
METADATA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ManualFields:
    """What a person read off the receipt. Every field optional: evidence is often partial.

    `amount_irr` is an `int` here and a string on the wire. `MONEY_TIME_CONTRACT.md:17` makes
    integer strings the transport format and `app/core/money.py` refuses a JSON number, so the
    route parses and this takes the parsed value.
    """

    beneficiary_name: str | None = None
    destination_iban: str | None = None
    amount_irr: int | None = None
    tracking_number: str | None = None
    payment_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AttachExternalEvidence:
    bank_result_bundle_id: uuid.UUID
    source_file_id: uuid.UUID
    fields: ManualFields
    bank_result_bundle_file_id: uuid.UUID | None = None
    page_number: int | None = None


def attach_external(
    command: AttachExternalEvidence,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> ReceiptSegment:
    """`POST /api/v1/bank-result-bundles/{id}/receipt-segments/external`. `:1733`.

    **No rectangle, and the CHECK permits that.** §12.4's bbox constraint has an all-null branch
    precisely for this method: the evidence is the whole file, so there is nothing to crop and a
    segment with no coordinates is a complete record rather than a partial one.

    **`rotation_degrees` stays 0**, which the `rotation_needs_a_rectangle` CHECK requires. An angle
    without a rectangle would be provenance describing nothing.

    **The bundle's counts are recomputed here.** This is the first caller that changes what
    `recount` counts, and doing it in the same transaction is what
    `04_Database_Schema.md:1179` asks for.
    """

    session = uow.session

    bundle = session.get(BankResultBundle, command.bank_result_bundle_id)
    if bundle is None:
        raise NotFoundError()
    if bundle.status == BUNDLE_CLOSED:
        raise BusinessRuleViolationError(
            f"bundle {bundle.bundle_number} is closed; it records what was concluded and does not "
            "accept new evidence"
        )

    record = session.get(FileObject, command.source_file_id)
    if record is None:
        raise NotFoundError()
    if record.scan_status != CLEAN_SCAN_STATUS:
        # The same check `upload_bundle` makes, for the same reason: evidence nobody has scanned is
        # evidence nobody may open. Checked rather than trusted, because the caller supplies the id.
        raise BusinessRuleViolationError(
            f"file {command.source_file_id} has scan status {record.scan_status!r}; evidence must "
            "be scanned clean before it is attached"
        )

    if command.bank_result_bundle_file_id is not None:
        membership = session.get(BankResultBundleFile, command.bank_result_bundle_file_id)
        if membership is None:
            raise NotFoundError()
        if membership.bank_result_bundle_id != bundle.id:
            raise BusinessRuleViolationError(
                "the bundle file named belongs to a different bundle"
            )
        if membership.file_id != command.source_file_id:
            # Otherwise the row would claim its evidence came from a position in the bundle that
            # holds a different file, which is provenance that points at the wrong thing.
            raise BusinessRuleViolationError(
                "the bundle file named does not hold the source file named"
            )

    segment = ReceiptSegment(
        bank_result_bundle_id=bundle.id,
        bank_result_bundle_file_id=command.bank_result_bundle_file_id,
        source_file_id=command.source_file_id,
        segment_file_id=None,
        page_number=command.page_number,
        rotation_degrees=0,
        creation_method=METHOD_EXTERNAL,
        # `created`, not `unmatched`: nothing has looked for a match yet, and M9's matching is what
        # moves it. Q-2 records why `created` is also where a pending crop rests.
        status=SEGMENT_CREATED,
        extracted_beneficiary_name=command.fields.beneficiary_name,
        extracted_destination_iban=command.fields.destination_iban,
        extracted_amount_irr=command.fields.amount_irr,
        extracted_tracking_number=command.fields.tracking_number,
        extracted_payment_at=command.fields.payment_at,
        raw_extraction={},
        # No confidence: a person typed these. `extraction_confidence` is for a later phase that
        # guesses, and a hard-coded 1.0 would be a machine claiming certainty on a human's behalf.
        extraction_confidence=None,
        created_by_actor_type=actor.actor_type,
        created_by_actor_id=actor.actor_id,
        record_version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(segment)
    session.flush()

    recount(session, bundle, now=now)

    AuditWriter(session, policy).record(
        AuditEntry(
            action=ATTACH_EXTERNAL_EVIDENCE.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="receipt_segment",
            entity_id=segment.id,
            entity_record_version=segment.record_version,
            previous_values=None,
            new_values={
                "bank_result_bundle_id": str(bundle.id),
                "creation_method": segment.creation_method,
                "status": segment.status,
                # The redaction policy masks the IBAN; the amount is recorded because an audit of
                # evidence that omitted the figure would answer no useful question.
                "extracted_amount_irr": (
                    str(segment.extracted_amount_irr)
                    if segment.extracted_amount_irr is not None
                    else None
                ),
                "extracted_destination_iban": segment.extracted_destination_iban,
            },
            reason="external evidence attached whole; no crop and no rectangle",
            occurred_at=now,
            metadata={"operation": ATTACH_EXTERNAL_EVIDENCE.audit_action},
        ),
        actor=actor,
        context=context,
    )
    return segment


def segments_of(uow: SqlAlchemyUnitOfWork, bundle_id: uuid.UUID) -> list[ReceiptSegment]:
    """Every segment of one bundle, oldest first — the order a reviewer worked in."""

    return list(
        uow.session.scalars(
            select(ReceiptSegment)
            .where(ReceiptSegment.bank_result_bundle_id == bundle_id)
            .order_by(ReceiptSegment.created_at)
        ).all()
    )
