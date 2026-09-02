"""Importing the bank's own record of what arrived. `05_API_Specification.md:1990`.

M10 slice 3. Two commands: recording a statement file the centre uploaded, and starting a parse of
it as a versioned run.

**A reparse creates a run; it never edits one.** `04_Database_Schema.md:774` says so, document 06
§10.3 repeats it as the first of five import rules, and document 08 §8.2 states the consequence
this slice exists to guarantee: "Reprocessing never overwrites earlier rows." So
`create_import_run` reads the highest `run_number` for the file and inserts the next one. It has no
branch that updates an existing run, and the migration grants the runtime nothing on `run_number`,
`parser_version`, `source_hash` or `bank_mapping_id` — so even a caller that wanted to rewrite run
1 into run 2 could not.

**The guards come from document 08 §8.1-8.2, which the M10 plan did not cite until this slice.**
A parse happens "with exact BankProfileVersion and BankMapping", from ".xlsx for approved bank
mappings", against "a selected destination center account". Four guards follow from those three
phrases, and each is refused separately: a single combined check would tell an operator that
something was wrong without saying what.

**This slice parses nothing.** It creates the run in `queued` and enqueues the job that will. Rows
are slice 4, and a parser written here would be a parser with nowhere to put its output — the
defect this repository has shipped five times, in the other direction.

Covers: DB-IMPORT-001, SVC-IMPORT-001, TRACE-IMPORT-001, SEC-IMPORT-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import CREATE_BANK_STATEMENT_FILE, CREATE_STATEMENT_IMPORT_RUN
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.claiming import new_job
from app.db.models.bank import BankAccount, BankMapping, BankProfileVersion
from app.db.models.bank_statement import (
    FILE_ARCHIVED,
    FILE_UPLOADED,
    RUN_IN_FLIGHT,
    RUN_QUEUED,
    BankStatementFile,
    BankStatementImportRun,
)
from app.db.models.file_object import CLEAN_SCAN_STATUS, FileObject
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.bank_statement"
METADATA_VERSION = 1

UPLOAD_OPERATION = "bank_statement.upload"
IMPORT_OPERATION = "bank_statement.import"

# `bank_mappings.file_type` under DOC-CONFLICT-047's settled reading: the *mapping type*, not the
# file format. An export mapping pointed at a statement would read the wrong columns and report a
# mismatch that looks like a bad file.
STATEMENT_MAPPING_TYPE: Final = "statement_import"

# Document 08 §8.1: "a selected destination center account". M2's `ACCOUNT_ROLES` spells the two
# roles that can receive one.
INCOMING_ACCOUNT_ROLES: Final = ("incoming_destination", "both")

# §8.1 says "approved bank mappings". M2's configuration vocabulary is `draft` / `active` /
# `retired`, and `active` is its word for a mapping approved and in use — a draft has not been
# reviewed, and a retired one was replaced, usually because it stopped matching the bank's file.
#
# `bank_mappings.approved_by_admin_user_id` records *who* approved it, and is M4's
# separation-of-duties concern rather than this command's. It is not re-checked here; the limit is
# recorded rather than left to be discovered.
APPROVED_MAPPING_STATUS: Final = "active"

# The parser this run will use. Recorded on the run and never granted, so a row produced today can
# be told apart from one a later parser produces against the same file — §10.5's whole reason for
# the column, and M8's `renderer_version` precedent.
PARSER_NAME: Final = "gold-statement-xlsx"
PARSER_VERSION: Final = "1.0.0"

# The parse runs on the file queue, like M8's crop: it reads an uploaded object and is far too slow
# for a request. `celery_app.py` routes `app.workers.tasks.files.*` there.
IMPORT_JOB_TYPE: Final = "bank_statement.parse_import_run"
IMPORT_QUEUE: Final = "files"


@dataclass(frozen=True, slots=True)
class CreateBankStatementFile:
    """§21.4's upload body.

    **No `status`.** A statement arrives `uploaded` and there is no other value an upload could
    honestly set; a field for one would be a value this command would then have to refuse.
    """

    bank_profile_version_id: uuid.UUID
    bank_account_id: uuid.UUID
    original_file_id: uuid.UUID
    date_range_start: date | None = None
    date_range_end: date | None = None


@dataclass(frozen=True, slots=True)
class CreateStatementImportRun:
    """§21.4's import-run body.

    **No `run_number` and no `parser_version`.** Both are the platform's to decide. A caller that
    could choose a run number could collide with a previous run through the unique; a caller that
    could choose a parser version could label this run's rows as another parser's, which is the one
    thing `TRACE-IMPORT-001` exists to prevent.
    """

    bank_statement_file_id: uuid.UUID
    bank_mapping_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class StatementFileResult:
    statement_file: BankStatementFile
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ImportRunResult:
    import_run: BankStatementImportRun
    replayed: bool = False


def create_statement_file(
    command: CreateBankStatementFile,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> StatementFileResult:
    """§21.4. The centre records a statement it uploaded. Nothing is parsed."""

    _refuse_half_a_date_range(command)

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=UPLOAD_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "bank_profile_version_id": str(command.bank_profile_version_id),
            "original_file_id": str(command.original_file_id),
        },
    )

    session = uow.session
    if claim.is_replay:
        return StatementFileResult(statement_file=_replayed_file(session, claim), replayed=True)

    version = session.get(BankProfileVersion, command.bank_profile_version_id)
    if version is None:
        raise NotFoundError()

    account = _incoming_destination_account(session, command.bank_account_id)
    _refuse_an_account_from_another_bank(account, version)
    _refuse_a_file_nobody_scanned(session, command.original_file_id)

    statement = BankStatementFile(
        bank_profile_version_id=version.id,
        bank_account_id=account.id,
        original_file_id=command.original_file_id,
        # **`uploaded`, and nothing else.** Document 06 §10.3 moves a file to `parsed` only when a
        # run succeeds, and this command runs no parse.
        status=FILE_UPLOADED,
        date_range_start=command.date_range_start,
        date_range_end=command.date_range_end,
        uploaded_by_admin_user_id=actor.actor_id,
        record_version=1,
    )
    session.add(statement)
    uow.flush()

    _audit_upload(session, policy, statement=statement, actor=actor, context=context, now=now)

    resolver.complete(
        claim,
        response_code=201,
        response_body={"statement_file_id": str(statement.id)},
        resource_type="bank_statement_file",
        resource_id=statement.id,
        now=now,
    )
    return StatementFileResult(statement_file=statement)


def create_import_run(
    command: CreateStatementImportRun,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> ImportRunResult:
    """§21.4. A new run, every time. `SVC-IMPORT-001`."""

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=IMPORT_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "bank_statement_file_id": str(command.bank_statement_file_id),
            "bank_mapping_id": str(command.bank_mapping_id),
        },
    )

    session = uow.session
    if claim.is_replay:
        return ImportRunResult(import_run=_replayed_run(session, claim), replayed=True)

    statement = session.get(BankStatementFile, command.bank_statement_file_id)
    if statement is None:
        raise NotFoundError()
    if statement.status == FILE_ARCHIVED:
        raise BusinessRuleViolationError(
            f"statement file {statement.id} is {FILE_ARCHIVED}; an operationally retired statement "
            "is not reparsed. Document 06 §10.3 draws no edge out of it."
        )

    mapping = _approved_statement_mapping(session, command.bank_mapping_id)
    _refuse_a_mapping_for_another_bank_version(mapping, statement)
    _refuse_a_second_run_while_one_is_in_flight(session, statement)

    source_hash = _source_hash(session, statement)

    run = BankStatementImportRun(
        bank_statement_file_id=statement.id,
        bank_mapping_id=mapping.id,
        # **The next number, never a reused one.** `UNIQUE(bank_statement_file_id, run_number)` is
        # what makes a losing racer fail rather than overwrite; this only chooses the value.
        run_number=_next_run_number(session, statement),
        status=RUN_QUEUED,
        # Null: this run has parsed nothing. Zero would say it parsed and found none.
        row_count=None,
        parser_version=PARSER_VERSION,
        source_hash=source_hash,
        created_by_admin_user_id=actor.actor_id,
        created_by_job_id=None,
    )
    session.add(run)
    uow.flush()

    job = new_job(
        job_type=IMPORT_JOB_TYPE,
        queue_name=IMPORT_QUEUE,
        input_payload={
            "bank_statement_import_run_id": str(run.id),
            "bank_statement_file_id": str(statement.id),
            "bank_mapping_id": str(mapping.id),
            # The same spelling the run records, so an operator comparing the job with the run is
            # comparing like with like — M8's crop makes the same argument about `render_scale`.
            "parser_version": PARSER_VERSION,
        },
        # One job per run. The route's `Idempotency-Key` covers a retried *request*; this covers a
        # retried *enqueue*, which is a different event. A reparse is a new run and therefore a new
        # key, which is the point: reparsing is meant to work.
        idempotency_key=f"{IMPORT_JOB_TYPE}:{run.id}",
        entity_type="bank_statement_import_run",
        entity_id=run.id,
    )
    job.provider = PARSER_NAME
    job.provider_version = PARSER_VERSION
    session.add(job)
    uow.flush()

    run.created_by_job_id = job.id
    uow.flush()

    _audit_run(session, policy, run=run, statement=statement, actor=actor, context=context, now=now)

    resolver.complete(
        claim,
        response_code=202,
        response_body={"import_run_id": str(run.id), "run_number": run.run_number},
        resource_type="bank_statement_import_run",
        resource_id=run.id,
        now=now,
    )
    return ImportRunResult(import_run=run)


def _refuse_half_a_date_range(command: CreateBankStatementFile) -> None:
    """§8.1's range is optional; half of one is not a range.

    The table's CHECK refuses it too. Refused here as well so the operator is told which field is
    missing rather than reading an integrity error, which is the difference between a 422 and a
    500.
    """

    start_given = command.date_range_start is not None
    end_given = command.date_range_end is not None
    if start_given != end_given:
        raise BusinessRuleViolationError(
            "a statement range needs both ends or neither; one end alone does not say which "
            "period the bank's file covers"
        )
    if start_given and end_given and command.date_range_start > command.date_range_end:  # type: ignore[operator]
        raise BusinessRuleViolationError(
            "a statement range cannot end before it starts"
        )


def _incoming_destination_account(session: Session, account_id: uuid.UUID) -> BankAccount:
    """`SEC-IMPORT-001`. §8.1's "selected destination center account"."""

    account = session.get(BankAccount, account_id)
    if account is None:
        raise NotFoundError()
    if account.account_role not in INCOMING_ACCOUNT_ROLES:
        raise BusinessRuleViolationError(
            f"account {account.id} has role {account.account_role!r}; a statement is imported "
            f"against an account money arrives at ({', '.join(INCOMING_ACCOUNT_ROLES)}). Filing an "
            "incoming statement under an outgoing-only account would put the bank's record of "
            "receipts in the ledger the platform reads when it pays people."
        )
    return account


def _refuse_an_account_from_another_bank(
    account: BankAccount, version: BankProfileVersion
) -> None:
    """`SEC-IMPORT-001`. The account and the profile version must be the same bank.

    Not in either document as a sentence, and it follows from both: §8.2 parses with an *exact*
    bank-profile version, and an account at a different bank cannot be what that version's file
    describes. Without this the two selections §8.1 asks for could disagree and nothing would say
    so until a row failed to match anything.
    """

    if account.bank_profile_id != version.bank_profile_id:
        raise BusinessRuleViolationError(
            f"account {account.id} belongs to bank profile {account.bank_profile_id} and the "
            f"selected version belongs to {version.bank_profile_id}; a statement cannot be one "
            "bank's file filed against another bank's account"
        )


def _refuse_a_file_nobody_scanned(session: Session, file_id: uuid.UUID) -> None:
    """`SEC-IMPORT-001`. The uploaded object must exist and have passed the scanner.

    M8's bundle upload refuses the same way and for the same reason: the parse that follows opens
    this file, and opening an unscanned upload is how a malicious spreadsheet reaches a worker.
    """

    record = session.get(FileObject, file_id)
    if record is None:
        raise NotFoundError()
    if record.scan_status != CLEAN_SCAN_STATUS:
        raise BusinessRuleViolationError(
            f"file {file_id} has scan status {record.scan_status!r}; a bank statement may only "
            f"cite an object whose scan is {CLEAN_SCAN_STATUS!r}"
        )


def _approved_statement_mapping(session: Session, mapping_id: uuid.UUID) -> BankMapping:
    """`SEC-IMPORT-001`. §8.1's "approved bank mappings", and the right kind of mapping."""

    mapping = session.get(BankMapping, mapping_id)
    if mapping is None:
        raise NotFoundError()
    if mapping.status != APPROVED_MAPPING_STATUS:
        raise BusinessRuleViolationError(
            f"mapping {mapping.id} is {mapping.status!r}; §8.1 imports statements with approved "
            f"mappings, which this configuration spells {APPROVED_MAPPING_STATUS!r}. A draft has "
            "not been reviewed and a retired one was replaced because it stopped matching the "
            "bank's file."
        )
    if mapping.file_type != STATEMENT_MAPPING_TYPE:
        raise BusinessRuleViolationError(
            f"mapping {mapping.id} is a {mapping.file_type!r} mapping; parsing a statement with "
            f"one requires a {STATEMENT_MAPPING_TYPE!r} mapping. An export mapping reads different "
            "columns and would report a template mismatch that looks like a bad statement."
        )
    return mapping


def _refuse_a_mapping_for_another_bank_version(
    mapping: BankMapping, statement: BankStatementFile
) -> None:
    """`SEC-IMPORT-001`, and the closest thing this slice has to `BANK-VER-005` itself.

    §8.2: parse "with exact BankProfileVersion and BankMapping". A mapping written for another
    bank's version — or for an older version of the same bank — describes a file this is not. The
    register's `BANK-VER-005` is exactly the question of whether the mapping fits the file, and
    this is the half of it a schema can answer.
    """

    if mapping.bank_profile_version_id != statement.bank_profile_version_id:
        raise BusinessRuleViolationError(
            f"mapping {mapping.id} belongs to bank-profile version "
            f"{mapping.bank_profile_version_id} and statement {statement.id} was uploaded against "
            f"{statement.bank_profile_version_id}; §8.2 parses with the exact version, and a "
            "mapping from another one would read the bank's columns in the wrong places"
        )


def _refuse_a_second_run_while_one_is_in_flight(
    session: Session, statement: BankStatementFile
) -> None:
    """The implementation's own guard, and recorded as such.

    Neither document forbids two concurrent parses of one file. Both are silent, and silence is
    not permission when the result is ambiguous: two runs finishing against the same statement
    produce two row sets, and Phase 1A has no rule saying which is authoritative. Matching would
    then have to choose, and it has nothing to choose with.

    **This does not restrict reparsing**, which is the workflow both documents do specify. A run
    that has succeeded, failed or been cancelled is not in flight, and the next run starts
    immediately.
    """

    in_flight = session.scalars(
        select(BankStatementImportRun)
        .where(BankStatementImportRun.bank_statement_file_id == statement.id)
        .where(BankStatementImportRun.status.in_(RUN_IN_FLIGHT))
    ).first()
    if in_flight is not None:
        raise BusinessRuleViolationError(
            f"import run {in_flight.id} for this statement is {in_flight.status!r}; a second parse "
            "would produce a second row set for one file with nothing to say which is "
            "authoritative. Reparse once it has finished — that is a new run and is unaffected."
        )


def _next_run_number(session: Session, statement: BankStatementFile) -> int:
    """`DB-IMPORT-001`. One more than the highest, starting at one.

    Read rather than counted: counting rows would reuse a number if a run were ever deleted, and
    the unique would then refuse the insert for a reason no operator could act on.
    """

    highest = session.scalar(
        select(func.max(BankStatementImportRun.run_number)).where(
            BankStatementImportRun.bank_statement_file_id == statement.id
        )
    )
    return 1 if highest is None else int(highest) + 1


def _source_hash(session: Session, statement: BankStatementFile) -> str:
    """`TRACE-IMPORT-001`. The file's digest as this run reads it.

    `command_catalog.yaml` makes `original_statement_unchanged` a precondition of creating a run.
    Recording the hash is what makes that checkable *after* the fact rather than only at the moment
    of the check: two runs whose `source_hash` differs read two different files, whatever the file
    id says.
    """

    record = session.get(FileObject, statement.original_file_id)
    if record is None:  # pragma: no cover - the foreign key holds it
        raise NotFoundError()
    if not record.sha256_hash:
        raise BusinessRuleViolationError(
            f"file {record.id} has no sha256 recorded, so a run against it could not later be "
            "shown to have read the same bytes. §10.5 asks every run for a source hash."
        )
    return record.sha256_hash


def _replayed_file(session: Session, claim: Any) -> BankStatementFile:
    stored = claim.record.response_body or {}
    statement = session.get(BankStatementFile, uuid.UUID(str(stored["statement_file_id"])))
    if statement is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return statement


def _replayed_run(session: Session, claim: Any) -> BankStatementImportRun:
    stored = claim.record.response_body or {}
    run = session.get(BankStatementImportRun, uuid.UUID(str(stored["import_run_id"])))
    if run is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return run


def _audit_upload(
    session: Session,
    policy: RedactionPolicy,
    *,
    statement: BankStatementFile,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    AuditWriter(session, policy).record(
        AuditEntry(
            action=CREATE_BANK_STATEMENT_FILE.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="bank_statement_file",
            entity_id=statement.id,
            entity_record_version=statement.record_version,
            previous_values={},
            new_values={
                "status": statement.status,
                "bank_profile_version_id": str(statement.bank_profile_version_id),
                "bank_account_id": str(statement.bank_account_id),
                "original_file_id": str(statement.original_file_id),
            },
            reason=None,
            occurred_at=now,
            metadata={"operation": CREATE_BANK_STATEMENT_FILE.audit_action},
        ),
        actor=actor,
        context=context,
    )


def _audit_run(
    session: Session,
    policy: RedactionPolicy,
    *,
    run: BankStatementImportRun,
    statement: BankStatementFile,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """The entry carries the provenance, because the provenance is the point.

    `run_number`, `parser_version` and `source_hash` are all here. A later reader asking why run 2
    produced different rows than run 1 is asking a question these three answer, and an audit entry
    that recorded only "a run was created" would not.
    """

    AuditWriter(session, policy).record(
        AuditEntry(
            action=CREATE_STATEMENT_IMPORT_RUN.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="bank_statement_import_run",
            entity_id=run.id,
            entity_record_version=None,
            previous_values={},
            new_values={
                "status": run.status,
                "bank_statement_file_id": str(statement.id),
                "bank_mapping_id": str(run.bank_mapping_id),
                "run_number": str(run.run_number),
                "parser_version": run.parser_version,
                "source_hash": run.source_hash,
            },
            reason=None,
            occurred_at=now,
            metadata={"operation": CREATE_STATEMENT_IMPORT_RUN.audit_action},
        ),
        actor=actor,
        context=context,
    )
