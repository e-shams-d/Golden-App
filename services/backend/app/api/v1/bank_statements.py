"""Bank statement upload and import runs. `05_API_Specification.md` §21.4.

M10 slice 3. Four of §21.4's five routes. The fifth — reading an import run's rows — is slice 4's,
because rows do not exist yet and a route that returned an empty list for every run would be
indistinguishable from one whose parser had failed.

**Internal only, all four.** `permission_catalog.yaml` gives `bank_statement.upload` and
`bank_statement.import` to the accountant and `bank_statement.read` to the accountant and the
manager, and gives none of them to a trader. So this router uses `requires(...)` throughout rather
than the dual ownership guard `gold_sale_orders.py` needs: there is no trader audience to deny, and
a statement is the centre's own record rather than anybody's property.

**Creating a run answers 202, not 201.** The run exists, and nothing has been parsed: it is
`queued` and a worker will pick it up. 201 would say the thing the caller asked for is ready, and
what is ready is a promise to parse.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import bank_statement as bank_statement_commands
from app.core.errors import (
    ErrorEnvelope,
    ForbiddenError,
    NotFoundError,
    PreconditionRequiredError,
)
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.bank_statement import BankStatementFile, BankStatementImportRun
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(prefix="/bank-statements", tags=["bank-statements"])

# A statement file record names an account and a bank version, and carries no IBAN of its own. The
# policy is passed explicitly for the reason every other call site passes one: POL-003 is open, and
# a default inherited silently would read as approved.
STATEMENT_REDACTION = RedactionPolicy(mask_iban=True)

RESPONSES: dict[int | str, dict[str, object]] = {
    400: {
        "model": ErrorEnvelope,
        "description": "The mapping, the account or the statement is not one this import can use.",
    },
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks the permission."},
    404: {"model": ErrorEnvelope, "description": "No such statement, mapping, account or file."},
    428: {"model": ErrorEnvelope, "description": "Idempotency-Key is required."},
    **VALIDATION_ERROR_RESPONSE,
}


class StatementFileRequest(BaseModel):
    """§8.1's four selections, and nothing else.

    **No `status`, no `parser_version`, no `source_hash`.** A statement arrives `uploaded`; the
    other two describe a parse that has not happened. Every one of them would be a value the
    command then had to refuse, and the strongest refusal is having nowhere for it to arrive.
    """

    model_config = ConfigDict(extra="forbid")

    bank_profile_version_id: uuid.UUID
    bank_account_id: uuid.UUID
    original_file_id: uuid.UUID
    # §8.1's "optional operator-supplied statement range". Both or neither, checked in the command
    # so the operator is told which end is missing.
    date_range_start: date | None = None
    date_range_end: date | None = None


class StatementFileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    bank_profile_version_id: uuid.UUID
    bank_account_id: uuid.UUID
    original_file_id: uuid.UUID
    status: str
    date_range_start: date | None
    date_range_end: date | None
    record_version: int
    created_at: datetime


class ImportRunRequest(BaseModel):
    """§21.4's import-run body: the mapping to parse with, and that is all.

    **No `run_number`.** `04_Database_Schema.md:774` makes a reparse a new run, and a caller that
    could name the number could aim a new run at an old one's slot. The platform chooses it.
    """

    model_config = ConfigDict(extra="forbid")

    bank_mapping_id: uuid.UUID


class ImportRunResponse(BaseModel):
    """What comes back. `row_count` is included **and will be null**.

    Present rather than omitted so a caller can see that this run has parsed nothing yet — zero
    would say it parsed and found none, and omitting the field would say the question was never
    asked.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    bank_statement_file_id: uuid.UUID
    bank_mapping_id: uuid.UUID
    run_number: int
    status: str
    row_count: int | None
    parser_version: str
    source_hash: str
    started_at: datetime | None
    finished_at: datetime | None
    error_summary: dict[str, Any] | None
    created_by_job_id: uuid.UUID | None
    created_at: datetime


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        role_snapshot=tuple(actor.roles),
        session_id=actor.session_id,
    )


def _require_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise PreconditionRequiredError(
            "Idempotency-Key is required; `command_catalog.yaml` marks the import-run command "
            "`idempotency: required`, and an upload retried without one would file the bank's "
            "statement twice"
        )
    return idempotency_key


def _rendered_file(statement: BankStatementFile) -> StatementFileResponse:
    return StatementFileResponse(
        id=statement.id,
        bank_profile_version_id=statement.bank_profile_version_id,
        bank_account_id=statement.bank_account_id,
        original_file_id=statement.original_file_id,
        status=statement.status,
        date_range_start=statement.date_range_start,
        date_range_end=statement.date_range_end,
        record_version=statement.record_version,
        created_at=statement.created_at,
    )


def _rendered_run(run: BankStatementImportRun) -> ImportRunResponse:
    return ImportRunResponse(
        id=run.id,
        bank_statement_file_id=run.bank_statement_file_id,
        bank_mapping_id=run.bank_mapping_id,
        run_number=run.run_number,
        status=run.status,
        row_count=run.row_count,
        parser_version=run.parser_version,
        source_hash=run.source_hash,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_summary=run.error_summary,
        created_by_job_id=run.created_by_job_id,
        created_at=run.created_at,
    )


@router.post(
    "",
    response_model=StatementFileResponse,
    status_code=201,
    operation_id="createBankStatement",
    summary="Record a statement file the centre uploaded.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_statement.upload"))],
)
def create_bank_statement(
    payload: StatementFileRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> StatementFileResponse:
    """`POST /api/v1/bank-statements`, per `:1990`.

    201: the record exists and the file is preserved. Nothing has been read out of it — §8.2 makes
    the parse a separate step, and this route deliberately does not start one. An upload that
    parsed itself would give an operator no place to choose the mapping, which is the selection
    §8.2 calls exact.
    """

    key = _require_key(idempotency_key)
    now = utc_now()

    if actor.actor_id is None:
        raise ForbiddenError()

    with runtime.uow_factory() as uow:
        result = bank_statement_commands.create_statement_file(
            bank_statement_commands.CreateBankStatementFile(
                bank_profile_version_id=payload.bank_profile_version_id,
                bank_account_id=payload.bank_account_id,
                original_file_id=payload.original_file_id,
                date_range_start=payload.date_range_start,
                date_range_end=payload.date_range_end,
            ),
            uow=uow,
            policy=STATEMENT_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        response = _rendered_file(result.statement_file)
        uow.commit()

    return response


@router.get(
    "",
    response_model=list[StatementFileResponse],
    operation_id="listBankStatements",
    summary="Statements the centre has uploaded.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_statement.read"))],
)
def list_bank_statements(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> list[StatementFileResponse]:
    """`GET /api/v1/bank-statements`, per `:1990`.

    No scoping predicate, and that is not an omission: a statement belongs to the centre, not to a
    trader, and `bank_statement.read` is granted to internal roles alone.
    """

    with runtime.uow_factory() as uow:
        rows = list(
            uow.session.scalars(
                select(BankStatementFile).order_by(BankStatementFile.created_at.desc())
            )
        )
        response = [_rendered_file(row) for row in rows]
        uow.rollback()

    return response


@router.get(
    "/{statement_id}",
    response_model=StatementFileResponse,
    operation_id="getBankStatement",
    summary="One statement file.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_statement.read"))],
)
def get_bank_statement(
    statement_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> StatementFileResponse:
    """`GET /api/v1/bank-statements/{statement_id}`, per `:1990`."""

    with runtime.uow_factory() as uow:
        statement = uow.session.get(BankStatementFile, statement_id)
        if statement is None:
            uow.rollback()
            raise NotFoundError()
        response = _rendered_file(statement)
        uow.rollback()

    return response


@router.post(
    "/{statement_id}/import-runs",
    response_model=ImportRunResponse,
    status_code=202,
    operation_id="createStatementImportRun",
    summary="Parse the statement, as a new run.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_statement.import"))],
)
def create_import_run(
    statement_id: uuid.UUID,
    payload: ImportRunRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ImportRunResponse:
    """`POST /api/v1/bank-statements/{statement_id}/import-runs`, per `:1990`.

    **No `If-Match`.** `command_catalog.yaml` gives this command
    `concurrency: immutable_new_import_run_per_parse`, not an If-Match rule, and the difference is
    the design: a record version guards an edit, and this creates a row rather than editing one.
    What stops two parses colliding is `UNIQUE(bank_statement_file_id, run_number)`, which a stale
    version header could not have expressed.

    202: the run is `queued`. §8.2 puts the parse after the run exists, and this route creates the
    run and enqueues the job — it does not parse.
    """

    key = _require_key(idempotency_key)
    now = utc_now()

    if actor.actor_id is None:
        raise ForbiddenError()

    with runtime.uow_factory() as uow:
        result = bank_statement_commands.create_import_run(
            bank_statement_commands.CreateStatementImportRun(
                bank_statement_file_id=statement_id,
                bank_mapping_id=payload.bank_mapping_id,
            ),
            uow=uow,
            policy=STATEMENT_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        response = _rendered_run(result.import_run)
        uow.commit()

    return response


@router.get(
    "/{statement_id}/import-runs",
    response_model=list[ImportRunResponse],
    operation_id="listStatementImportRuns",
    summary="Every parse of this statement, oldest first.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_statement.read"))],
)
def list_import_runs(
    statement_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> list[ImportRunResponse]:
    """Not in §21.4's five, and the reason it is here is `SVC-IMPORT-001`.

    §21.4 lists the rows of *one* run, which is slice 4's. But "a reparse creates a new run and
    does not overwrite the old one" is a claim about the *set* of runs, and an operator with no way
    to see run 1 beside run 2 has to take that on trust. Ordered oldest first, so the history reads
    forwards.
    """

    with runtime.uow_factory() as uow:
        statement = uow.session.get(BankStatementFile, statement_id)
        if statement is None:
            uow.rollback()
            raise NotFoundError()
        rows = list(
            uow.session.scalars(
                select(BankStatementImportRun)
                .where(BankStatementImportRun.bank_statement_file_id == statement_id)
                .order_by(BankStatementImportRun.run_number.asc())
            )
        )
        response = [_rendered_run(row) for row in rows]
        uow.rollback()

    return response
