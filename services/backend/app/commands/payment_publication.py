"""Turning a confirmed result into something a trader may be shown. §17.6, §20.1-20.2.

M9 slice 5. `05_API_Specification.md:1874` (preview) and `:1879` (publish),
`15_Agent_Implementation_Plan.md:1153` (what a publication contains),
`04_Database_Schema.md:1133` (the table) and `:1154` (its three uniques), and
`08_Bank_File_and_Result_Processing.md:1307` — **§19.3, "Publication guards", which the M9 plan
never cited and which is the authoritative list.** Eight of them, and where each is enforced:

    financial result is human-confirmed      _refuse_an_unconfirmed_result
    trader owns the request                  structural: a publication is per request
    evidence is safe for trader visibility   _safe_evidence_file_id, crop only
    full mixed bundle is not included        the same function, by refusing rather than degrading
    required evidence policy is satisfied    settled at confirmation; see below
    no unresolved privacy warning exists     _refuse_unverified_privacy
    publication preview has been reviewed    PUBLISHABLE_FROM, one status wide
    idempotency key and expected version     Idempotency-Key and If-Match, both required

**The privacy guard is the caller M8 built a mechanism for and could not call.**
`app/commands/manual_review_task.py`'s `privacy_verification` says so in its own docstring:
"There is deliberately no setter. §2.5 of the M8 plan: publication is M9's, and a guard on a path
that does not exist would be untestable." That path exists now. It compares the reviewed segment
version against the segment's version *today*, so a crop re-rendered after its review is unverified
again with nothing to remember to reset.

**"Required evidence policy is satisfied" is not re-decided here.** Slice 3's G-3 makes a paid
confirmation carry either an evidence link or a written reason; by the time a result can be
published, that question has already been answered and audited. Re-asking it at publication would
give two answers to one question, which is the shape `_recalculate` refused for the paid sum.

**The snapshot is derived, never submitted.** Doc 05 §20.2 says it in one sentence: "The server
derives amount, beneficiary, attempts, status, bank, tracking, and dates from authoritative
records. The client cannot submit arbitrary financial summary values." Enforced the way slice 3
enforced "amount is exact" and slice 3B enforced the beneficiary — **there are no financial fields
in either request model**, so there is nothing for a client to disagree with. `SVC-PUBLICATION-003`
asserts the absence over the models rather than testing a rejected value.

**The content hash is blind to who published and when, and that is the slice's central decision.**

`04_Database_Schema.md:1155` gives `UNIQUE(payment_request_id, content_hash)`, and the M9 plan says
what it is for: it "stops a correction that changed nothing from producing a version N+1 that says
the same thing". That constraint can only ever fire if the digest covers content alone. Put
`published_at` in the hashed payload and every republication is unique by its clock; put
`publication_version` in and every republication is unique by its counter. Either way the
constraint becomes decorative while still looking present, which is the failure this repository
keeps finding — a gate whose input makes it unable to fail.

So §17 `:1153`'s ten items are split across two places rather than one:

    hashed (summary_payload)   request number, beneficiary, masked IBAN, amount, paid total,
                               attempt results, bank, tracking data, safe evidence file
    not hashed (columns)       publication version, published actor, published time

A trader still sees all ten — the API composes both halves — and `SVC-PUBLICATION-002` is the test
that fails if either of the three ever migrates into the payload.

**The IBAN is masked in the payload, not at read time.** `app/db/models/audit_log.py` gives the
reason for the audit trail and it holds here with more force: this row is retained for years and
handed to an external party. A read-time mask would leave the full account number in a JSONB column
forever, one careless serializer away from the trader.

**The evidence file is the crop, and the refusal when there is none is the point.**
`receipt_segments` carries three file ids: `bank_result_bundle_file_id` and `source_file_id` are
the bank's mixed document — every trader's payments in one file — and `segment_file_id` is the crop
M8 cut out of it. Publishing a segment with no crop would leave only a bundle to point at, so it is
refused rather than degraded. That is §17 `:1185`'s "full bundle never reaches trader APIs or
files" enforced where the choice is made, and `SEC-PUBLICATION-001` scans for it besides.

**The request must be `paid`, through `result_ready_for_trader`.**
`06_Workflows_and_State_Machines.md:600-601` draws exactly two arrows into publication —
`paid -> result_ready_for_trader: publication preview validated` and
`result_ready_for_trader -> result_published: immutable publication created` — so the preview is
not a read: it is the validation step that makes a request publishable, and publishing without it
is a transition the workflow document does not have.

`partially_paid` and `failed` have **no** arrow into publication in 13.2, and after checking what
the rest of the system does about it, that is the design rather than a gap — G-5 in the M9 plan
carries the full argument. In short: a publication is an immutable, hashed, evidence-bearing
statement of a completed settlement, and §11.9 calls it a "share output". A failure is not a
result to share; it is an event to tell somebody about, and `PaymentAttemptFailed` is already
enqueued by slice 3 with slice 7's `notifications` as its consumer. `partially_paid` is not final
at all — the state machine's own next step from it is a retry.

Deriving `failed` on the request and publishing that would also have been a branch with no
reachable input: **nothing in this system writes `payment_requests.status = 'failed'`**, and
§17.4's five payment-result commands include no command that would, though 13.2 draws the arrow.
Recorded in G-5 rather than closed by inventing a sixth command.

Covers: SVC-PUBLICATION-001, SVC-PUBLICATION-002, SVC-PUBLICATION-003, SVC-PUBLICATION-004,
SEC-PUBLICATION-001, AUD-PUBLICATION-002.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.outbox import OutboxMessage, OutboxWriter
from app.audit.redaction import RedactionPolicy, mask_iban_value
from app.audit.registry import PUBLISH_PAYMENT_RESULT
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.commands.manual_review_task import privacy_verification
from app.core.errors import BusinessRuleViolationError, ConflictError, NotFoundError
from app.core.hashing import unversioned_digest
from app.core.hashing import unversioned_digest as payload_digest
from app.db.concurrency import compare_and_swap
from app.db.locking import LockScope, LockTarget, lock_rows
from app.db.models.bank import BankProfile, BankProfileVersion
from app.db.models.confirmed_evidence_link import LINK_ACTIVE, ConfirmedEvidenceLink
from app.db.models.file_object import FileObject
from app.db.models.payment_batch import PaymentAttempt
from app.db.models.payment_request import PaymentRequest, PaymentRequestRevision
from app.db.models.payment_result_publication import (
    PUBLICATION_ACTIVE,
    PaymentResultPublication,
)
from app.db.models.receipt_segment import ReceiptSegment
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.exports.share_card import (
    FONT_NAME,
    RENDERER_VERSION,
    SHARE_MEDIA_TYPE,
    render_share_card,
)
from app.files.derivation import SHARE_CARD, DerivationRequest, record_derivation
from app.files.download import FileBytesUnavailableError, open_stream
from app.idempotency import IdempotencyResolver
from app.storage.interface import StorageBackend

METADATA_SCHEMA = "audit.payment_publication"
METADATA_VERSION = 1

PUBLISH_OPERATION = "payment_publication.publish"

# `06_Workflows_and_State_Machines.md:600`. A preview validates a `paid` request; running it again
# on one already validated is re-previewing, not a second transition, so both are accepted.
PREVIEWABLE_FROM: tuple[str, ...] = ("paid", "result_ready_for_trader")

# `:601`. The only status a publication may be created from.
PUBLISHABLE_FROM: tuple[str, ...] = ("result_ready_for_trader",)

REQUEST_PAID = "paid"
REQUEST_READY_FOR_TRADER = "result_ready_for_trader"
REQUEST_RESULT_PUBLISHED = "result_published"

ATTEMPT_PAID = "paid"

# `status_catalog.yaml`'s `receipt_segment` aggregate. `confirmed_linked` is what slice 2 leaves a
# segment in; `published` is the one nothing wrote until this slice — see
# `_mark_the_segment_published`.
SEGMENT_CONFIRMED_LINKED = "confirmed_linked"
SEGMENT_PUBLISHED = "published"

# The attempt states a trader is shown. A `created` or `batched` attempt is internal scheduling and
# says nothing about what a bank did; `superseded` is a row a retry retired. Publishing them would
# describe the centre's workflow rather than the trader's money.
REPORTABLE_ATTEMPT_STATUSES: tuple[str, ...] = ("paid", "failed")


class PublicationRefused(BusinessRuleViolationError):
    """A publication that must not be created, with the reason in the message."""


@dataclass(frozen=True, slots=True)
class PreviewPublication:
    """§20.1's body. **No fields beyond the request**, because a preview proposes nothing."""

    payment_request_id: uuid.UUID
    primary_evidence_link_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class PublishResult:
    """§20.2's body, minus what this slice does not build.

    `include_share_file` and `share_format` are **absent**: slice 5B builds the renderer, and a
    flag a caller may set that changes nothing is worse than no flag at all — it reads as a
    working feature. `message_to_trader` is here because §20.2 shows it and it is the one field a
    publisher genuinely supplies; it is *not* hashed, for the same reason the timestamp is not.
    """

    payment_request_id: uuid.UUID
    expected_record_version: int
    published_by_admin_user_id: uuid.UUID
    primary_evidence_link_id: uuid.UUID | None = None
    message_to_trader: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationPreview:
    """What a publisher is shown before they commit to it."""

    payment_request_id: uuid.UUID
    next_publication_version: int
    content_hash: str
    summary_payload: dict[str, Any]
    request_status: str


@dataclass(frozen=True, slots=True)
class PublishedResult:
    publication: PaymentResultPublication
    request_status: str
    replayed: bool = False


def preview_publication(
    command: PreviewPublication,
    *,
    uow: SqlAlchemyUnitOfWork,
) -> PublicationPreview:
    """§20.1. Builds the snapshot, validates it, moves the request, persists no publication.

    **It writes one thing** — `payment_requests.status` — and the workflow document is why:
    `paid -> result_ready_for_trader: publication preview validated`. Without that write the next
    status would be unreachable and publish would have to accept `paid` directly, which 13.2 has no
    arrow for.

    Everything else about it is a read. Doc 05 §20.1: "It is not persisted as active publication."
    """

    session = uow.session
    request = _locked_request(session, command.payment_request_id)

    if request.status not in PREVIEWABLE_FROM:
        raise PublicationRefused(
            f"request {request.request_number} is {request.status}; only "
            f"{', '.join(PREVIEWABLE_FROM)} may be previewed. "
            "`06_Workflows_and_State_Machines.md:600` draws the only arrow into publication from "
            "`paid`, and that is the design rather than an omission: a publication is an "
            "immutable, hashed, evidence-bearing statement of a completed settlement. A failure "
            "is not a result to publish, it is an event to tell somebody about — "
            "`PaymentAttemptFailed` is already enqueued when one is confirmed, and slice 7's "
            "`notifications` is its consumer. G-5 in the M9 plan records the whole argument."
        )

    _refuse_an_unconfirmed_result(session, request)
    link = _evidence_that_points_here(session, request, command.primary_evidence_link_id)
    _refuse_unverified_privacy(session, link)
    payload = _snapshot(session, request, link)

    request.status = REQUEST_READY_FOR_TRADER

    return PublicationPreview(
        payment_request_id=request.id,
        next_publication_version=_next_version(session, request.id),
        content_hash=unversioned_digest(payload),
        summary_payload=payload,
        request_status=request.status,
    )


def publish_result(
    command: PublishResult,
    *,
    uow: SqlAlchemyUnitOfWork,
    storage: StorageBackend,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> PublishedResult:
    """§20.2. One immutable row, and the three uniques decide what may not follow it."""

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=PUBLISH_OPERATION,
        idempotency_key=idempotency_key,
        payload={"payment_request_id": str(command.payment_request_id)},
    )

    session = uow.session

    if claim.is_replay:
        publication, request = _replayed(session, claim)
        return PublishedResult(
            publication=publication, request_status=request.status, replayed=True
        )

    request = _locked_request(session, command.payment_request_id)

    if request.status not in PUBLISHABLE_FROM:
        raise PublicationRefused(
            f"request {request.request_number} is {request.status}; "
            f"`06_Workflows_and_State_Machines.md:601` creates a publication only from "
            f"{', '.join(PUBLISHABLE_FROM)}. Preview the result first — that step is what "
            "validates the snapshot, and skipping it would publish something nobody looked at."
        )

    _refuse_an_unconfirmed_result(session, request)
    link = _evidence_that_points_here(session, request, command.primary_evidence_link_id)
    _refuse_unverified_privacy(session, link)
    payload = _snapshot(session, request, link)
    content_hash = unversioned_digest(payload)

    publication = PaymentResultPublication(
        payment_request_id=request.id,
        publication_version=_next_version(session, request.id),
        status=PUBLICATION_ACTIVE,
        summary_payload=payload,
        primary_evidence_link_id=link.id if link is not None else None,
        content_hash=content_hash,
        published_by_admin_user_id=command.published_by_admin_user_id,
        published_at=now,
        # **Rendered before the insert, not set afterwards.** `20260831_0031` grants the runtime no
        # UPDATE on this table at all, so a card attached in a second statement would need a grant
        # this slice has no other use for — and the first thing that grant would also permit is
        # rewriting a publication's status outside a correction. Rendering first keeps the row
        # insert-only and the immutability intact.
        share_file_id=_render_the_share_card(
            uow, storage, payload=payload, link=link, request=request, now=now
        ),
    )
    session.add(publication)
    _flush_or_conflict(uow, str(request.request_number))

    # §12.6 gave this column to slice 2 unwritten and named this slice as its writer. It is what
    # says an evidence row has left the building — a link a trader has seen cannot be revoked
    # quietly, and slice 7's correction is the only thing that may supersede what it supports.
    if link is not None:
        link.published_to_trader_at = now
        _mark_the_segment_published(session, link)

    # `08_Bank_File_and_Result_Processing.md:1316`: "idempotency key and expected version are
    # valid". The key is claimed above; this is the version half, and it is a compare-and-swap
    # rather than a comparison followed by an assignment — the predicate travels inside the UPDATE,
    # so there is no window between reading the version and writing the status.
    compare_and_swap(
        session,
        PaymentRequest,
        entity_id=request.id,
        expected_version=command.expected_record_version,
        values={
            "status": REQUEST_RESULT_PUBLISHED,
            "result_published_at": now,
            **(
                {"trader_result_note": command.message_to_trader}
                if command.message_to_trader is not None
                else {}
            ),
        },
    )
    uow.flush()
    session.refresh(request)

    _audit(
        session,
        policy,
        publication=publication,
        request=request,
        previous_status=REQUEST_READY_FOR_TRADER,
        reason=command.message_to_trader,
        actor=actor,
        context=context,
        now=now,
    )

    OutboxWriter(session, policy).enqueue(
        OutboxMessage(
            aggregate_type="payment_result_publication",
            aggregate_id=publication.id,
            aggregate_version=publication.publication_version,
            event_type=str(PUBLISH_PAYMENT_RESULT.outbox_event_type),
            payload={
                "publication_id": str(publication.id),
                "payment_request_id": str(request.id),
                "publication_version": publication.publication_version,
                "content_hash": content_hash,
            },
            payload_version=1,
            headers={},
        )
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={
            "publication_id": str(publication.id),
            "request_id": str(request.id),
        },
        resource_type="payment_result_publication",
        resource_id=publication.id,
        now=now,
    )
    return PublishedResult(publication=publication, request_status=request.status)


def _locked_request(session: Session, request_id: uuid.UUID) -> PaymentRequest:
    """`lock_request_and_current_result_snapshot`, which is the catalogue's own concurrency note.

    `REQUEST_PAID_TOTAL` is M2's scope for the request aggregate and the same one slice 3 takes
    before recalculating: two publishes racing must not both read "no active publication".
    """

    lock_rows(
        session,
        [LockTarget.of(LockScope.REQUEST_PAID_TOTAL, PaymentRequest, request_id)],
        models={PaymentRequest.__tablename__: PaymentRequest},
    )
    request = session.get(PaymentRequest, request_id)
    if request is None:
        raise NotFoundError()
    return request


def _next_version(session: Session, request_id: uuid.UUID) -> int:
    """§11.9: "Monotonic per request".

    Computed under the request lock and confirmed by `uq_publication_version_per_request` — the
    count is what usually gets it right and the unique is what makes it always right.
    """

    highest = session.scalar(
        select(func.max(PaymentResultPublication.publication_version)).where(
            PaymentResultPublication.payment_request_id == request_id
        )
    )
    return int(highest or 0) + 1


def _evidence_that_points_here(
    session: Session,
    request: PaymentRequest,
    link_id: uuid.UUID | None,
) -> ConfirmedEvidenceLink | None:
    """The link must be active and belong to an attempt of *this* request.

    Slice 3 refuses evidence pointing at a different attempt; here the aggregate is one level up,
    so the question is whether the attempt belongs to this request. A publication citing another
    trader's evidence would be the isolation failure §17 `:1185` names, arriving through a field
    that looks entirely legitimate.
    """

    if link_id is None:
        return None

    link = session.get(ConfirmedEvidenceLink, link_id)
    if link is None:
        raise NotFoundError()
    if link.status != LINK_ACTIVE:
        raise PublicationRefused(
            f"evidence link {link.id} is {link.status}; a publication may only cite an active "
            "link. `04_Database_Schema.md:1306` keeps replaced links forever precisely so that "
            "an old publication still resolves — a new one must cite what is current."
        )

    attempt = session.get(PaymentAttempt, link.payment_attempt_id)
    if attempt is None:  # pragma: no cover - the foreign key guarantees it
        raise NotFoundError()
    if attempt.payment_request_id != request.id:
        raise PublicationRefused(
            "the evidence link belongs to a different payment request. §17 `:1185` requires a "
            "trader to see only their own result, and citing another request's evidence would "
            "put somebody else's receipt in this trader's publication."
        )
    return link


def _refuse_an_unconfirmed_result(session: Session, request: PaymentRequest) -> None:
    """`08_Bank_File_and_Result_Processing.md:1309`: "financial result is human-confirmed".

    Checked against `confirmed_by_admin_user_id` rather than against the request's status. The
    status is *derived* — slice 4's `_recalculate` computes it from the attempts — so asking it
    whether a human confirmed anything is asking a calculation to vouch for a person. The column
    §11.3 calls the human confirmation is the only thing that can answer.
    """

    confirmed = session.scalar(
        select(func.count())
        .select_from(PaymentAttempt)
        .where(
            PaymentAttempt.payment_request_id == request.id,
            PaymentAttempt.status == ATTEMPT_PAID,
            PaymentAttempt.confirmed_by_admin_user_id.is_not(None),
        )
    )
    if not confirmed:
        raise PublicationRefused(
            f"request {request.request_number} has no attempt confirmed paid by a person. "
            "§19.3's first publication guard is that the financial result is human-confirmed, and "
            "a status computed from rows nobody confirmed is not a confirmation."
        )


def _refuse_unverified_privacy(
    session: Session, link: ConfirmedEvidenceLink | None
) -> None:
    """§19.3: "no unresolved privacy warning exists". §16.5 is where the requirement comes from.

    **This is the caller M8 built and could not write.** `privacy_verification`'s own docstring
    records the gap in as many words — "There is deliberately no setter... publication is M9's, and
    a guard on a path that does not exist would be untestable" — and M8's
    `TestNothingCanPublish` stood in for it by asserting no publication path existed at all. The
    path exists now, so the stand-in becomes the real thing.

    The verification is a **version comparison**, not a flag: a resolved `segment_privacy_review`
    task records the segment version its reviewer looked at, and it holds only while the segment
    still has that version. A crop re-rendered after its review is unverified again automatically.

    A publication citing **no** evidence needs no privacy review, because there is no image to
    review. The refusal is about showing a picture, not about publishing.
    """

    if link is None:
        return

    verification = privacy_verification(session, link.receipt_segment_id)
    if not verification.verified:
        raise PublicationRefused(
            f"receipt segment {link.receipt_segment_id} has no privacy review that applies to it "
            "as it now stands. §19.3 requires that no unresolved privacy warning exists before a "
            "publication, and §16.5 makes the check per segment version — a crop re-rendered "
            "after its review is unverified again. Resolve a `segment_privacy_review` task "
            "against the current version first."
        )


def _safe_evidence_file_id(
    session: Session, link: ConfirmedEvidenceLink | None
) -> uuid.UUID | None:
    """The crop, or a refusal. Never the bundle.

    `receipt_segments` holds three file ids and only one of them is trader-safe:

        bank_result_bundle_file_id   every trader's results in one document
        source_file_id               the same document, or the page it came from
        segment_file_id              the crop M8 cut, showing this payment alone

    §17 `:1185` requires that the full bundle never reaches trader APIs or files. A segment with no
    crop offers nothing else to show, so publishing it is refused rather than falling back — a
    fallback here is exactly how a bundle would reach a trader.
    """

    if link is None:
        return None

    segment = session.get(ReceiptSegment, link.receipt_segment_id)
    if segment is None:  # pragma: no cover - the foreign key guarantees it
        raise NotFoundError()
    if segment.segment_file_id is None:
        raise PublicationRefused(
            f"receipt segment {segment.id} has no crop, so there is no trader-safe file to "
            "publish. §17 `:1185` forbids the full bundle reaching a trader, and the bundle is "
            "the only other file this segment has — create the crop first."
        )
    return segment.segment_file_id


def _render_the_share_card(
    uow: SqlAlchemyUnitOfWork,
    storage: StorageBackend,
    *,
    payload: dict[str, Any],
    link: ConfirmedEvidenceLink | None,
    request: PaymentRequest,
    now: datetime,
) -> uuid.UUID | None:
    """`FILE-PUBLICATION-001` and `-002`. The card, and the row that accounts for it.

    **A derivation of the crop, not an upload.** `record_derivation` gives the card its source's
    category and visibility, so it inherits `incoming_payment_receipt` and
    `trader_visible_after_publication` — both already approved — instead of needing an eighth entry
    in document 05's upload-purpose list, which `FILE-PURPOSE-001` parses and would refuse.

    **No evidence, no card.** A publication may cite nothing; a result card whose whole subject is
    the evidence would then be a page of fields with a blank space where the proof should be, and
    `share_file_id` is nullable precisely so that case has an answer. The trader still sees the
    publication itself.

    The parameters recorded on the derivation are the publication's **content hash** and version,
    not the payload: `parameters_hash` refuses floats and the payload is already stored on the row
    this card belongs to. What the derivation needs to say is *which* publication produced these
    bytes, and the digest says it in 64 characters.
    """

    if link is None:
        return None

    segment = uow.session.get(ReceiptSegment, link.receipt_segment_id)
    if segment is None or segment.segment_file_id is None:  # pragma: no cover - guarded above
        raise NotFoundError()

    crop = uow.session.get(FileObject, segment.segment_file_id)
    if crop is None:  # pragma: no cover - the foreign key guarantees it
        raise NotFoundError()

    # **`open_stream`, not `storage.open`.** A gate refuses a storage address outside
    # `app/storage/` and `app/files/`, and its reason is exact: `StorageError` carries the key in
    # its message, so an unhandled one puts a storage path in front of a caller.
    try:
        evidence = b"".join(open_stream(storage, crop).chunks)
    except FileBytesUnavailableError:
        # The crop's row exists and its bytes do not. Refused rather than rendered without the
        # evidence: a card that silently dropped the proof would look complete and be exactly the
        # thing a trader forwards to argue with.
        raise PublicationRefused(
            f"the evidence crop {crop.id} has a record but no stored bytes, so the share card "
            "would show a result with no proof. `reconcile-storage.sh` finds this state; it is "
            "not something to render around."
        ) from None

    card = render_share_card(payload, evidence)

    result = record_derivation(
        DerivationRequest(
            source_file_id=crop.id,
            derivation_type=SHARE_CARD,
            renderer_version=RENDERER_VERSION,
            parameters={
                "payment_request_id": str(request.id),
                "publication_content_hash": payload_digest(payload),
                "rendered_at_version": FONT_NAME,
            },
            media_type=SHARE_MEDIA_TYPE,
            filename=f"{request.request_number}-result.png",
            body=io.BytesIO(card),
        ),
        uow=uow,
        storage=storage,
        moment=now,
    )
    return result.derived_file_id


def _flush_or_conflict(uow: SqlAlchemyUnitOfWork, request_number: str) -> None:
    """Turn the three uniques' refusal into a sentence an accountant can act on.

    Without this the response is a 500 from an `IntegrityError`, which tells the publisher nothing
    and sends an operator looking in the wrong place. Slice 2 wrote the same helper for the same
    reason: the index is doing exactly its job, and the message is what was missing.

    All three collisions share one message deliberately. `uq_active_publication_per_request` and
    `uq_publication_content_per_request` both mean "this request already says this", and which of
    them fires first depends on the order PostgreSQL happens to check — a message that named one
    index would be right half the time.

    **Takes the request *number*, not the request.** A failed flush expires every loaded
    attribute, so reading `request.request_number` here sends SQLAlchemy back to a session that
    can no longer answer — and the 409 becomes a `PendingRollbackError` 500. Slice 2's version
    takes a plain string for the same reason; this one learned it by producing that 500.
    """

    try:
        uow.flush()
    except IntegrityError as exc:  # pragma: no cover - exercised by the live conflict test
        raise ConflictError(
            f"request {request_number} already has a published result with this content. "
            "`04_Database_Schema.md:1154` permits one active publication per request and refuses a "
            "second version whose content is identical — a correction that changed nothing is not "
            "a new answer. Correct the result first, then publish version N+1."
        ) from exc


def _mark_the_segment_published(session: Session, link: ConfirmedEvidenceLink) -> None:
    """`06_Workflows_and_State_Machines.md:1066`: `confirmed_linked --> published`.

    **`published` was a segment status nothing wrote.** `status_catalog.yaml` approves it,
    `receipt_segments`' CHECK admits it, `RESOLVED_SEGMENT_STATUSES` counts it, and slice 2's
    comment says "M9 owns `confirmed_linked` and `published`" — then wrote only the first. The
    status-with-no-writer is the same defect as the mechanism with no caller, and it was found the
    way the others were: by a test failing on the *other* status and the list being read properly.

    Guarded by the transition rather than set unconditionally. A segment already `published` —
    cited by an earlier publication of another attempt — stays where it is, and a `superseded` or
    `voided` one is not dragged back into the living by a publication that should not have cited
    it in the first place.
    """

    segment = session.get(ReceiptSegment, link.receipt_segment_id)
    if segment is None:  # pragma: no cover - the foreign key guarantees it
        raise NotFoundError()
    if segment.status == SEGMENT_CONFIRMED_LINKED:
        segment.status = SEGMENT_PUBLISHED


def _snapshot(
    session: Session,
    request: PaymentRequest,
    link: ConfirmedEvidenceLink | None,
) -> dict[str, Any]:
    """§17 `:1153`'s trader-safe content, and nothing that would make the hash unique by accident.

    **Every number is a string.** `app/core/hashing.py` refuses a float outright, and an integer
    that survives a JSONB round-trip as a float would change the digest without changing the
    meaning — the rule M8 slice 4 found the hard way with a scale factor. Amounts are IRR integers
    spelled as decimal strings, which is also how the outbox writes them.

    **No `published_at`, no `publication_version`, no actor.** See the module docstring: those
    three would each make `uq_publication_content_per_request` unable to fire.
    """

    revision = session.get(PaymentRequestRevision, request.current_revision_id)
    if revision is None:  # pragma: no cover - the composite key guarantees one
        raise NotFoundError()

    attempts = list(
        session.scalars(
            select(PaymentAttempt)
            .where(
                PaymentAttempt.payment_request_id == request.id,
                PaymentAttempt.status.in_(REPORTABLE_ATTEMPT_STATUSES),
            )
            .order_by(PaymentAttempt.attempt_number)
        )
    )

    paid_total = sum(
        attempt.amount_irr for attempt in attempts if attempt.status == ATTEMPT_PAID
    )

    return {
        "request_number": request.request_number,
        "beneficiary_name": revision.beneficiary_name_snapshot,
        # Masked at write time. The full IBAN never enters this column, so no later reader can
        # expose one that was never stored.
        "beneficiary_iban_masked": mask_iban_value(revision.beneficiary_iban_snapshot),
        "amount_irr": str(revision.amount_irr),
        "paid_total_irr": str(paid_total),
        "attempts": [
            {
                "attempt_number": attempt.attempt_number,
                "status": attempt.status,
                "amount_irr": str(attempt.amount_irr),
                "bank_name": _bank_name(session, attempt),
                "bank_tracking_number": attempt.bank_tracking_number,
                "bank_result_at": (
                    attempt.bank_result_at.isoformat() if attempt.bank_result_at else None
                ),
                "failure_code": attempt.failure_code,
            }
            for attempt in attempts
        ],
        "evidence_file_id": _string_or_none(_safe_evidence_file_id(session, link)),
    }


def _bank_name(session: Session, attempt: PaymentAttempt) -> str | None:
    """The bank a payment left from, by name only.

    §17 `:1153` lists "bank and tracking data" among what a publication contains, and a receipt
    that does not say which bank paid is hard to reconcile against a statement. The **name** and
    nothing else: `bank_accounts` holds the centre's own account number and IBAN, and those are
    the centre's, not this trader's business.
    """

    version = session.get(BankProfileVersion, attempt.bank_profile_version_id)
    if version is None:  # pragma: no cover - the foreign key guarantees it
        return None
    profile = session.get(BankProfile, version.bank_profile_id)
    return str(profile.name) if profile is not None else None


def _string_or_none(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _replayed(
    session: Session, claim: Any
) -> tuple[PaymentResultPublication, PaymentRequest]:
    stored = claim.record.response_body or {}
    publication = session.get(
        PaymentResultPublication, uuid.UUID(str(stored["publication_id"]))
    )
    request = session.get(PaymentRequest, uuid.UUID(str(stored["request_id"])))
    if publication is None or request is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return publication, request


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    publication: PaymentResultPublication,
    request: PaymentRequest,
    previous_status: str,
    reason: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """`AUD-PUBLICATION-002`. The hash goes in the audit row, the payload does not.

    The payload is already stored, immutably, on the row this entry names. Copying it into the
    audit trail would duplicate a trader's financial details into a second retained place for no
    gain — the digest is what an investigator needs to prove the stored payload is the one that
    was published.
    """

    AuditWriter(session, policy).record(
        AuditEntry(
            action=PUBLISH_PAYMENT_RESULT.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="payment_result_publication",
            entity_id=publication.id,
            entity_record_version=publication.publication_version,
            previous_values={"status": previous_status},
            new_values={
                "status": request.status,
                "payment_request_id": str(request.id),
                "publication_version": publication.publication_version,
                "content_hash": publication.content_hash,
                "primary_evidence_link_id": _string_or_none(
                    publication.primary_evidence_link_id
                ),
            },
            reason=reason,
            occurred_at=now,
            metadata={"operation": PUBLISH_PAYMENT_RESULT.audit_action},
        ),
        actor=actor,
        context=context,
    )
