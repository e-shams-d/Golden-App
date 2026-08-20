"""Creating a batch: attempts, a draft version, its ordered items, and the allocations.

`05_API_Specification.md:1316-1345` and `command_catalog.yaml:105-116`. One command, one
transaction, and either all of it or none of it — `SVC-BATCH-001`.

**This is where the preview stops being advisory.** Document 05 ends the preview section with
"Preview is advisory and not approvable. The create command revalidates everything", so every
refusal `app/api/v1/payment_batches.py:_current` makes is made again here against rows read
inside this transaction. Revalidating is not defensive duplication: between the preview and the
create, a trader can file a correction, and the accountant is looking at a screen that was right
when it rendered.

**The allocation is the membership.** There is no `payment_batch_id` on an attempt
(`04_Database_Schema.md:909`), so what makes a request part of a batch is a row in
`payment_attempt_allocations` — and `FINANCIAL_INTEGRITY_BASELINE.md:38-40` puts the uniqueness
at the database boundary because "service-layer checks alone are insufficient". Nothing in this
module checks whether an attempt is already allocated. The partial unique index does, and the
`IntegrityError` it raises is the answer; a `SELECT` first would be a check two concurrent
transactions both pass.

**An attempt passes through `created`.** `06_Workflows_and_State_Machines.md:676-677` draws
`[*] --> created` and then `created --> included_in_batch_version`. So attempts are inserted at
`created`, flushed, and moved once their item and allocation exist. Inserting the final status
directly would be observably identical and would leave the machine's initial state unreachable
by any code path — a state nothing can produce is the mirror of a transition nothing implements,
and this milestone has already found both.

**Two amounts, and only one of them is trusted.** The split is recomputed here from the
revision's `amount_irr` and the profile version's rules. The preview's numbers are not carried
in the request and could not be: a client-supplied row amount would make the client the
authority on how much leaves the account.

Covers: SVC-BATCH-001, SVC-BATCH-002, SVC-BATCH-003, DB-BATCH-002, AUD-BATCH-001,
CON-BATCH-004.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.batching.splitting import SplittingRules, split
from app.core.errors import BusinessRuleViolationError, ConflictError, NotFoundError
from app.core.hashing import unversioned_digest
from app.core.time import to_business_time
from app.db.models.bank import BankAccount, BankMapping, BankProfileVersion
from app.db.models.payment_batch import (
    PaymentAttempt,
    PaymentAttemptAllocation,
    PaymentBatch,
    PaymentBatchItem,
    PaymentBatchVersion,
)
from app.db.models.payment_request import PaymentRequest, PaymentRequestRevision
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

# `06_Workflows_and_State_Machines.md:558-566` makes this the entry to batching, and M5's
# `mark-eligible-for-batching` is the only command that reaches it. Enumerated from the
# document rather than listed as taste: `SVC-BATCH-002` asserts it is the *only* origin.
ELIGIBLE_FOR_BATCHING = "eligible_for_batching"

# The initial states. Both are the initial state of their machine in document 06 — `:676` for
# the attempt, `:788` for the container — and neither is chosen here.
ATTEMPT_CREATED = "created"
ATTEMPT_INCLUDED = "included_in_batch_version"
BATCH_DRAFT = "draft"
VERSION_DRAFT = "draft"

# `04_Database_Schema.md:917`. Whether a row was split decides its kind, and the kind is
# frozen: a row that was `original` never becomes `split` later.
ATTEMPT_TYPE_ORIGINAL = "original"
ATTEMPT_TYPE_SPLIT = "split"

# `command_catalog.yaml:113` maps this command to exactly one audit action, and to
# `"outbox_event": null`. Nothing here publishes: the catalogue defines
# `PaymentBatchVersionReadyForApproval` for finalization and `PaymentBatchVersionApproved` for
# approval, and neither has happened. `payment_batch_version.created` exists in the audit
# catalogue and belongs to the *separate* `payment_batch_version.create` command — writing it
# here would claim that command ran.
AUDIT_ACTION = "payment_batch.created"
CREATE_BATCH_OPERATION = "payment_batch.create"

METADATA_SCHEMA = "payment_batch_command"
METADATA_VERSION = 1


@dataclass(frozen=True, slots=True)
class BatchSelection:
    """One request the accountant chose, with what they believed about it.

    Both expectations are required for the reason `CON-BATCH-001` gives on the preview: a batch
    built against a revision that has since been corrected is not stale, it is wrong, and it
    looks exactly like right.
    """

    payment_request_id: uuid.UUID
    expected_revision_id: uuid.UUID
    expected_record_version: int


@dataclass(frozen=True, slots=True)
class CreateBatch:
    """`05_API_Specification.md:1318-1322`: the same selection contract as the preview."""

    items: tuple[BatchSelection, ...]
    bank_profile_version_id: uuid.UUID
    bank_account_id: uuid.UUID
    bank_mapping_id: uuid.UUID
    apply_split_rules: bool = True


@dataclass(frozen=True, slots=True)
class BatchResult:
    """What the route renders. `replayed` distinguishes a retry from a second batch."""

    batch: PaymentBatch
    version: PaymentBatchVersion
    items: tuple[PaymentBatchItem, ...]
    replayed: bool = False


def create_batch(
    command: CreateBatch,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> BatchResult:
    """One batch, one draft version, its attempts, its items and its allocations — or none.

    Takes the unit of work rather than a session because the idempotency resolver needs a
    savepoint: it inserts the claim, flushes to force the unique violation while it can still be
    turned into a replay, and rolls back to the savepoint if the key was already claimed.

    The evaluation instant is an argument and is used for every split, so a batch created across
    a bank's cutoff second cannot apply two different limits to two of its own rows.
    """

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=CREATE_BATCH_OPERATION,
        idempotency_key=idempotency_key,
        # The selection and the configuration, and not the instant: a retry thirty seconds
        # later is the same request, and including `now` would make every retry look like new
        # content and raise a conflict where a replay is correct.
        payload={
            "items": [
                {
                    "payment_request_id": str(item.payment_request_id),
                    "expected_revision_id": str(item.expected_revision_id),
                    "expected_record_version": item.expected_record_version,
                }
                for item in command.items
            ],
            "bank_profile_version_id": str(command.bank_profile_version_id),
            "bank_account_id": str(command.bank_account_id),
            "bank_mapping_id": str(command.bank_mapping_id),
            "apply_split_rules": command.apply_split_rules,
        },
    )

    session = uow.session

    if claim.is_replay:
        return _replayed(session, claim.record.response_body or {})

    profile_version, _account, _mapping = _configuration(session, command)
    rules = SplittingRules(
        default_transfer_limit_irr=profile_version.default_transfer_limit_irr,
        after_cutoff_transfer_limit_irr=profile_version.after_cutoff_transfer_limit_irr,
        cutoff_time=profile_version.cutoff_time,
        splitting_enabled=profile_version.splitting_enabled and command.apply_split_rules,
    )

    batch = PaymentBatch(
        batch_number=_next_batch_number(session, now),
        # `draft` because the version being created is a draft. The column is a projection of
        # the current version's state — `status_catalog.yaml` marks nine of eleven container
        # states `derived: true` — so this is not an independent decision, and `CON-BATCH-004`
        # asserts the two cannot disagree.
        status=BATCH_DRAFT,
        created_by_admin_user_id=actor.actor_id,
    )
    session.add(batch)
    # `id` comes from `gen_random_uuid()`, so it does not exist until the row does. The version
    # below needs it, and the alternative — generating the id in Python — would move key
    # generation out of the database for one caller's convenience.
    uow.flush()

    attempts: list[PaymentAttempt] = []
    rows: list[tuple[PaymentAttempt, int, PaymentRequestRevision]] = []

    for selection in command.items:
        request, revision = _current(session, selection)
        proposed = split(int(revision.amount_irr), rules, now)
        # The kind is decided once, by whether this request produced more than one row. A
        # single row is `original` even when splitting was enabled and simply did not bite.
        kind = ATTEMPT_TYPE_SPLIT if len(proposed) > 1 else ATTEMPT_TYPE_ORIGINAL
        first_number = _next_attempt_number(session, request.id)

        for offset, row in enumerate(proposed):
            attempt = PaymentAttempt(
                payment_request_id=request.id,
                payment_request_revision_id=revision.id,
                attempt_number=first_number + offset,
                attempt_type=kind,
                amount_irr=row.amount_irr,
                # Frozen from the revision, not from the live beneficiary record. The file a
                # bank receives has to be explainable from rows alone months later.
                beneficiary_name_snapshot=revision.beneficiary_name_snapshot,
                beneficiary_iban_snapshot=revision.beneficiary_iban_snapshot,
                beneficiary_national_id_snapshot=revision.beneficiary_national_id_snapshot,
                bank_profile_version_id=command.bank_profile_version_id,
                bank_account_id=command.bank_account_id,
                # The rules as they read at this instant, and the reason this row's amount is
                # what it is. `DB-ATTEMPT-002`: an export rendered next month must be
                # reproducible without consulting a profile that may have been superseded.
                split_rule_snapshot={
                    "default_transfer_limit_irr": rules.default_transfer_limit_irr,
                    "after_cutoff_transfer_limit_irr": rules.after_cutoff_transfer_limit_irr,
                    "cutoff_time": (rules.cutoff_time.isoformat() if rules.cutoff_time else None),
                    "splitting_enabled": rules.splitting_enabled,
                    "split_reason": row.split_reason,
                    "evaluated_at": now.isoformat(),
                },
                status=ATTEMPT_CREATED,
            )
            session.add(attempt)
            attempts.append(attempt)
            rows.append((attempt, row.amount_irr, revision))

    # Forces the attempt inserts, so the items below have ids to reference and the `created`
    # status is a row the database held rather than a value that never reached it.
    uow.flush()

    # The version is built **after** its rows are known, so `row_count`, `total_amount_irr` and
    # `content_hash` are real values in the INSERT rather than zeros and an empty string patched
    # up by a later UPDATE. `FINANCIAL_INTEGRITY_BASELINE.md:22-23` forbids a placeholder hash in
    # as many words, and a row that briefly holds one is a row a crash can leave holding one.
    #
    # Nothing here needs the version's id: `row_hash` is a digest over what the row instructs a
    # bank to do, and the item's `payment_batch_version_id` is assigned below once the version
    # exists. So the ordering costs nothing and removes the placeholder entirely.
    prepared: list[dict[str, Any]] = []
    for order, (attempt, amount, revision) in enumerate(rows, start=1):
        prepared.append(
            {
                "payment_attempt_id": attempt.id,
                "row_order": order,
                "amount_irr": amount,
                "beneficiary_name_snapshot": attempt.beneficiary_name_snapshot,
                "beneficiary_iban_snapshot": attempt.beneficiary_iban_snapshot,
                "description_snapshot": revision.description,
                "attempt_snapshot": {
                    "payment_request_id": str(attempt.payment_request_id),
                    "payment_request_revision_id": str(attempt.payment_request_revision_id),
                    "attempt_number": attempt.attempt_number,
                    "attempt_type": attempt.attempt_type,
                    "bank_profile_version_id": str(attempt.bank_profile_version_id),
                    "bank_account_id": str(attempt.bank_account_id),
                    "split_rule_snapshot": attempt.split_rule_snapshot,
                },
                "row_hash": _row_hash(attempt, amount, order, revision.description),
            }
        )

    version = PaymentBatchVersion(
        payment_batch_id=batch.id,
        version_number=1,
        bank_profile_version_id=command.bank_profile_version_id,
        bank_account_id=command.bank_account_id,
        bank_mapping_id=command.bank_mapping_id,
        status=VERSION_DRAFT,
        row_count=len(prepared),
        total_amount_irr=sum(int(row["amount_irr"]) for row in prepared),
        content_hash=_content_hash(command, prepared),
        # Empty because slice 2 runs no validation. Slice 3 owns the summary, and an empty
        # object is the honest value for "nothing has been checked yet" — unlike a hash, which
        # has no honest empty value at all.
        validation_summary={"errors": [], "warnings": []},
        created_by_admin_user_id=actor.actor_id,
    )
    session.add(version)
    uow.flush()

    items: list[PaymentBatchItem] = []
    # `prepared_row`, not `row`: the split loop above binds `row` to a `ProposedRow`, and reusing
    # the name here gave one variable two types in one function. mypy refused it, which is the
    # cheap version — the expensive version is a later edit that reads the wrong `row`.
    for prepared_row in prepared:
        # `row_order` is continuous across the whole version, not restarted per request: the
        # order is the order of the lines a bank reads, and
        # `UNIQUE(payment_batch_version_id, row_order)` refuses a file with two row ones.
        item = PaymentBatchItem(payment_batch_version_id=version.id, **prepared_row)
        session.add(item)
        items.append(item)

    uow.flush()

    for item, attempt in zip(items, attempts, strict=True):
        # Nothing checks first. The partial unique index decides, and its `IntegrityError` is
        # the refusal — `FINANCIAL_INTEGRITY_BASELINE.md:39-40` calls a service-layer check
        # insufficient, and two concurrent transactions would both pass one.
        session.add(
            PaymentAttemptAllocation(
                payment_attempt_id=attempt.id,
                payment_batch_version_id=version.id,
                payment_batch_item_id=item.id,
                allocated_at=now,
                allocated_by_admin_user_id=actor.actor_id,
            )
        )
        # The transition document 06 draws. The attempt held `created` between the two flushes.
        attempt.status = ATTEMPT_INCLUDED

    # The container's pointer, last. The composite key is `DEFERRABLE INITIALLY DEFERRED`, so
    # the pair only has to agree at commit — but assigning it here rather than earlier means
    # there is no window in which the batch names a version that does not exist yet.
    batch.current_version_id = version.id

    uow.flush()

    # A cheap assertion about what was just written, kept in the command rather than only in a
    # test: the version's own counts must equal the rows it holds. `17.4` states the invariant
    # (`row_count = count(items)`, `total = sum(amounts)`) and slice 3 enforces it at
    # finalization; here it guards against the counts being computed from `prepared` while the
    # items were inserted from something else.
    if version.row_count != len(items) or version.total_amount_irr != sum(
        item.amount_irr for item in items
    ):  # pragma: no cover - both are computed from the same list
        raise BusinessRuleViolationError(
            f"version {version.id} claims {version.row_count} rows totalling "
            f"{version.total_amount_irr} and holds {len(items)} rows totalling "
            f"{sum(item.amount_irr for item in items)}"
        )

    _audit(
        session,
        policy,
        batch=batch,
        version=version,
        actor=actor,
        context=context,
        now=now,
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={
            "batch_id": str(batch.id),
            "version_id": str(version.id),
        },
        resource_type="payment_batch",
        resource_id=batch.id,
        now=now,
    )

    return BatchResult(batch=batch, version=version, items=tuple(items))


def _configuration(
    session: Session, command: CreateBatch
) -> tuple[BankProfileVersion, BankAccount, BankMapping]:
    """All three configuration rows, or a refusal.

    All three are required and NOT NULL on the version, because
    `FINANCIAL_INTEGRITY_BASELINE.md` §1 requires a final artifact to name what produced it. A
    version that cannot say which mapping rendered it cannot be re-rendered, and an approval
    over it would be an approval of something nobody can reproduce.

    The account and the mapping are read and not otherwise consulted in this slice: the split
    depends on the profile version's limits, and the mapping shapes the export M7 builds. Read
    anyway, because a foreign key that fails at flush time reports a constraint name and this
    reports which of the three the caller got wrong.
    """

    profile_version = session.get(BankProfileVersion, command.bank_profile_version_id)
    if profile_version is None:
        raise NotFoundError()
    account = session.get(BankAccount, command.bank_account_id)
    if account is None:
        raise NotFoundError()
    mapping = session.get(BankMapping, command.bank_mapping_id)
    if mapping is None:
        raise NotFoundError()
    return profile_version, account, mapping


def _current(
    session: Session, selection: BatchSelection
) -> tuple[PaymentRequest, PaymentRequestRevision]:
    """The request and revision named, revalidated inside this transaction.

    `SVC-BATCH-002` and `CON-BATCH-001`. Deliberately the same three refusals the preview
    makes, made again against rows read here — document 05 says the create command revalidates
    everything, and between the two calls a trader can file a correction.

    The status refusal is a `BusinessRuleViolationError` rather than the preview's `404`. The
    difference is what the caller may learn: a preview should not teach an id's existence, and a
    create was made from a preview the caller already saw, so naming the reason is useful rather
    than leaky.
    """

    record = session.get(PaymentRequest, selection.payment_request_id)
    if record is None:
        raise NotFoundError()

    if record.status != ELIGIBLE_FOR_BATCHING:
        raise BusinessRuleViolationError(
            f"request {record.request_number} is {record.status}; only a request at "
            f"{ELIGIBLE_FOR_BATCHING} may be allocated to a batch"
        )
    if record.record_version != selection.expected_record_version:
        raise ConflictError(
            f"request {record.request_number} has moved since it was read; "
            "re-read it before creating a batch"
        )
    if record.current_revision_id != selection.expected_revision_id:
        raise ConflictError(
            f"request {record.request_number} has a newer revision than the one named"
        )

    revision = session.get(PaymentRequestRevision, selection.expected_revision_id)
    if revision is None:  # pragma: no cover - the pointer's FK guarantees it
        raise NotFoundError()
    return record, revision


def _replayed(session: Session, stored: dict[str, Any]) -> BatchResult:
    """The first attempt's batch, read back from the ids the idempotency record kept.

    `SVC-BATCH-003`. A retry after a network timeout must not allocate the same attempts to a
    second batch — and it could not, because the partial unique index would refuse the second
    allocation. Which is exactly why the replay matters: without it the caller would receive a
    constraint violation for a batch their first call had already created successfully.
    """

    batch = session.get(PaymentBatch, uuid.UUID(str(stored["batch_id"])))
    version = session.get(PaymentBatchVersion, uuid.UUID(str(stored["version_id"])))
    if batch is None or version is None:  # pragma: no cover - the record made them
        raise NotFoundError()

    items = (
        session.execute(
            select(PaymentBatchItem)
            .where(PaymentBatchItem.payment_batch_version_id == version.id)
            .order_by(PaymentBatchItem.row_order)
        )
        .scalars()
        .all()
    )
    return BatchResult(batch=batch, version=version, items=tuple(items), replayed=True)


def _next_batch_number(session: Session, now: datetime) -> str:
    """`PB-YYYYMMDD-NNNNNN`, counted within the business day.

    The family is documented and this is the second place in the codebase to implement it:
    `05_API_Specification.md:304` gives the prefixes and `07_UI_UX_Specification.md:630-640`
    gives the day precision and the six-digit width. M5 invented `GP-YYYYMM-NNNN` for
    `request_number` instead of reading them, which is the defect
    `tests/backend/test_human_readable_numbers.py` now parses the documents to prevent.

    **Gregorian, and that is ADR-006's decision rather than this function's.** The documented
    examples are Jalali; ADR-006 is Approved and states that "Jalali presentation does not leak
    into database or transport contracts", and this value is both stored and transported. A
    frontend may render a Jalali form. `DOC-CONFLICT-054` records the disagreement.

    The date is the business day in Tehran, per ADR-006 point 3: a batch created at 23:00 UTC
    belongs to tomorrow's business day, and an operator reading the number back would otherwise
    be told the wrong day.

    The count is taken in this transaction, so two concurrent creations can compute the same
    number and `UNIQUE(batch_number)` refuses the second. The database owns uniqueness and the
    caller retries; a `SELECT max()+1` that pretended to be safe would be the version that
    silently collides.
    """

    prefix = f"PB-{to_business_time(now).strftime('%Y%m%d')}-"
    used = session.scalar(
        select(func.count())
        .select_from(PaymentBatch)
        .where(PaymentBatch.batch_number.startswith(prefix))
    )
    return f"{prefix}{(used or 0) + 1:06d}"


def _next_attempt_number(session: Session, payment_request_id: uuid.UUID) -> int:
    """The next `attempt_number` for this request, which `UNIQUE` then enforces.

    Counted rather than maximised for the same reason as the numbers above, and it matters more
    here: a request that has already been batched, released and re-batched has attempts whose
    numbers must not collide with the new ones. `max() + 1` over existing rows is what gives
    that, so this counts rows and the unique constraint is the guarantee.
    """

    used = session.scalar(
        select(func.count())
        .select_from(PaymentAttempt)
        .where(PaymentAttempt.payment_request_id == payment_request_id)
    )
    return (used or 0) + 1


def _row_hash(attempt: PaymentAttempt, amount: int, row_order: int, description: str | None) -> str:
    """A digest over what this row instructs a bank to do.

    `unversioned_digest` rather than `content_hash` because document 04 makes the column 64
    characters and the versioned form is 67 — the cost is recorded in that function's docstring.

    Slice 3 owns the *canonical* content hash and its determinism obligations. What slice 2 owes
    is that the column is never a placeholder: `FINANCIAL_INTEGRITY_BASELINE.md:22-23` forbids a
    placeholder hash in as many words, and a row inserted with an empty digest would be a row
    whose integrity nothing could later check.
    """

    return unversioned_digest(
        {
            "row_order": row_order,
            "payment_attempt_id": str(attempt.id),
            "amount_irr": amount,
            "beneficiary_name": attempt.beneficiary_name_snapshot,
            "beneficiary_iban": attempt.beneficiary_iban_snapshot,
            "description": description,
            "bank_profile_version_id": str(attempt.bank_profile_version_id),
            "bank_account_id": str(attempt.bank_account_id),
        }
    )


def _content_hash(command: CreateBatch, prepared: list[dict[str, Any]]) -> str:
    """A digest over the ordered rows and the configuration that will render them.

    `04_Database_Schema.md:1008` lists what the canonical hash includes: "ordered rows, attempt
    IDs/snapshots, amounts, beneficiary/IBAN snapshots, bank profile version, mapping version,
    source account, and relevant transfer channel/configuration". All of it is here, and slice 3
    adds the obligations that make it *canonical* — order-stability and determinism across
    processes — rather than adding the value itself.

    Takes the prepared rows rather than persisted items, so the version can be inserted with its
    real hash instead of an empty string patched up by a later UPDATE. Sorted by `row_order`
    explicitly rather than trusting the list order: reordering rows changes what a batch means,
    so the hash must depend on the order and must not depend on the order this function happened
    to receive.
    """

    return unversioned_digest(
        {
            "bank_profile_version_id": str(command.bank_profile_version_id),
            "bank_account_id": str(command.bank_account_id),
            "bank_mapping_id": str(command.bank_mapping_id),
            "rows": [
                {
                    "row_order": row["row_order"],
                    "payment_attempt_id": str(row["payment_attempt_id"]),
                    "amount_irr": int(row["amount_irr"]),
                    "beneficiary_name": row["beneficiary_name_snapshot"],
                    "beneficiary_iban": row["beneficiary_iban_snapshot"],
                    "description": row["description_snapshot"],
                    "row_hash": row["row_hash"],
                }
                for row in sorted(prepared, key=lambda row: int(row["row_order"]))
            ],
        }
    )


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    batch: PaymentBatch,
    version: PaymentBatchVersion,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """One row, in this transaction, with the action the catalogue maps to this command.

    `AUD-BATCH-001`. Exactly one action and no outbox event, because `command_catalog.yaml:113`
    says `"audit_action": "payment_batch.created"` and `"outbox_event": null`. M5's audit
    obligation claimed more than its catalogue allowed and had to be corrected mid-slice; this
    one is written from the catalogue outward.

    `payment_batch_version.created` is also a catalogued action and is deliberately not written
    here: it belongs to the separate `payment_batch_version.create` command, and emitting it
    would put a record in the log claiming a command ran that nobody invoked.
    """

    AuditWriter(session, policy).record(
        AuditEntry(
            action=AUDIT_ACTION,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="payment_batch",
            entity_id=batch.id,
            entity_record_version=batch.record_version,
            previous_values=None,
            new_values={
                "batch_number": batch.batch_number,
                "status": batch.status,
                "current_version_id": str(version.id),
                "row_count": version.row_count,
                # A string, for the same reason the API emits strings: this value is read by
                # whatever consumes the audit log, and a JSON number is a double there too.
                "total_amount_irr": str(version.total_amount_irr),
                "content_hash": version.content_hash,
            },
            reason=None,
            occurred_at=now,
            metadata={"operation": AUDIT_ACTION},
        ),
        actor=actor,
        context=context,
    )
