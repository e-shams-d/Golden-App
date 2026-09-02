"""Running a queued import run, and writing what it read. `08_Bank_File_and_Result_Processing.md`
§8.2, §22.2.

M10 slice 4. Slice 3 created the run and enqueued a job; this is the thing that does the work, and
building it in the same milestone is deliberate — a queue with a job type no worker handles is the
mechanism-with-no-caller defect this repository has shipped five times.

**Nothing here updates a row, ever.** `20260907_0038` grants the runtime no UPDATE on
`bank_statement_rows` at all, so the immutability §10.6 asks for is a privilege rather than a
discipline. This module inserts rows and never re-reads one to change it.

**A failed parse leaves the file re-parseable and the run honest.** Document 08 §22.2: preserve the
original file, preserve the import-run errors, allow a new import run after mapping correction. So
a mapping that does not fit the file fails *the run* — `failed`, with `error_summary` naming what
was wrong — and writes no rows at all. The statement file goes to `parse_failed`, from which
document 06 §10.3 draws an edge back to `parsed` when a later run succeeds.

**Rows are written for every source line, including the ones that could not be read.** §22.2's
fourth requirement is "never partially hide invalid rows". A run that wrote only its good rows
would report a `row_count` that silently disagreed with the file, and the operator would have no
way to see which lines went missing.

Covers: DB-ROW-001, SVC-ROW-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.models.bank import BankMapping
from app.db.models.bank_statement import (
    FILE_PARSE_FAILED,
    FILE_PARSED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    BankStatementFile,
    BankStatementImportRun,
    BankStatementRow,
)
from app.db.models.file_object import FileObject
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.files.download import open_stream
from app.statements.parser import MappingConfigurationError, ParsedRow, parse_statement
from app.storage.interface import StorageBackend


@dataclass(frozen=True, slots=True)
class ParseReport:
    """What one run produced. Counted rather than logged only, so a test can assert it."""

    import_run_id: uuid.UUID
    status: str
    row_count: int
    valid: int
    warned: int
    invalid: int
    ignored: int


def parse_pending_run(
    import_run_id: uuid.UUID,
    *,
    uow: SqlAlchemyUnitOfWork,
    storage: StorageBackend,
    now: datetime,
) -> ParseReport:
    """Read the statement this run points at and write its rows.

    Called by `app/workers/tasks/files.py` inside the transaction that claimed the job, so the
    rows, the run's status and the file's status commit together or not at all. A partial commit
    would leave a `succeeded` run with half a statement in it, which is the one outcome nothing
    downstream could detect.
    """

    session = uow.session
    run = session.get(BankStatementImportRun, import_run_id)
    if run is None:
        raise NotFoundError()
    if run.status != RUN_QUEUED:
        # Not an error and not work. A run already taken is what a redelivered job looks like, and
        # re-parsing it would violate the unique on `(run_id, row_number)` rather than doing
        # anything useful.
        return _report(run, [])

    statement = session.get(BankStatementFile, run.bank_statement_file_id)
    mapping = session.get(BankMapping, run.bank_mapping_id)
    if statement is None or mapping is None:  # pragma: no cover - foreign keys hold both
        raise NotFoundError()

    run.status = RUN_RUNNING
    run.started_at = now
    uow.flush()

    try:
        content = _statement_bytes(session, storage, statement)
        result = parse_statement(
            content,
            mapping=dict(mapping.mapping or {}),
            normalization_rules=dict(mapping.normalization_rules or {}),
        )
    except MappingConfigurationError as error:
        return _fail(uow, run=run, statement=statement, now=now, reason=str(error))

    for parsed in result.rows:
        session.add(_row_of(run, parsed))
    uow.flush()

    run.status = RUN_SUCCEEDED
    run.row_count = len(result.rows)
    run.finished_at = now
    # §22.2: "preserve import-run errors". Recorded even on a successful run, because a run that
    # read every line and flagged nine of them is not the same event as one that read every line
    # cleanly — and only this column can say which happened after the fact.
    run.error_summary = _summary(result.rows, unmapped=result.unmapped_headers)
    statement.status = FILE_PARSED
    statement.record_version += 1
    uow.flush()

    return _report(run, list(result.rows))


def _fail(
    uow: SqlAlchemyUnitOfWork,
    *,
    run: BankStatementImportRun,
    statement: BankStatementFile,
    now: datetime,
    reason: str,
) -> ParseReport:
    """The mapping cannot read this file. No rows, and both records say so.

    Document 06 §10.3 keeps `parse_failed` non-terminal on the file and draws the edge back to
    `parsed`, because §22.2's third requirement is that a new run after a mapping correction must
    be allowed. Slice 3's in-flight guard already permits it: a failed run is not in flight.
    """

    run.status = RUN_FAILED
    run.finished_at = now
    run.row_count = 0
    run.error_summary = {"mapping_error": reason}
    statement.status = FILE_PARSE_FAILED
    statement.record_version += 1
    uow.flush()
    return _report(run, [])


def _statement_bytes(
    session: Session, storage: StorageBackend, statement: BankStatementFile
) -> bytes:
    """The source bytes, through the file service rather than around it.

    `open_stream` and not `storage.open(record.storage_key)`: M4's boundary obligation forbids any
    module outside `app/storage/` and `app/files/` from handling a storage key, because ADR-003 has
    not chosen a production adapter and a change of provider must touch one place. M8's crop reads
    its source the same way and says so for the same reason.
    """

    record = session.get(FileObject, statement.original_file_id)
    if record is None:  # pragma: no cover - the foreign key holds it
        raise NotFoundError()
    return b"".join(open_stream(storage, record).chunks)


def _row_of(run: BankStatementImportRun, parsed: ParsedRow) -> BankStatementRow:
    return BankStatementRow(
        bank_statement_import_run_id=run.id,
        row_number=parsed.row_number,
        transaction_at_normalized=parsed.transaction_at_normalized,
        transaction_date_raw=parsed.transaction_date_raw,
        transaction_time_raw=parsed.transaction_time_raw,
        amount_in_irr=parsed.amount_in_irr,
        amount_out_irr=parsed.amount_out_irr,
        balance_irr=parsed.balance_irr,
        document_number=parsed.document_number,
        tracking_number=parsed.tracking_number,
        description=parsed.description,
        counterparty_name=parsed.counterparty_name,
        counterparty_account=parsed.counterparty_account,
        counterparty_iban=parsed.counterparty_iban,
        raw_data=parsed.raw_data,
        row_fingerprint=parsed.row_fingerprint,
        status=parsed.status,
    )


def _summary(rows: tuple[ParsedRow, ...], *, unmapped: tuple[str, ...]) -> dict[str, object]:
    """What an operator needs to see in preview, and nothing they would have to guess at.

    Rows are named by number and reason. `unmapped_headers` is not an error — §22.2 refuses to hide
    anything — and is usually the first sign a bank changed its file format.
    """

    problems = [
        {"row_number": row.row_number, "status": row.status, "problems": list(row.problems)}
        for row in rows
        if row.problems
    ]
    return {
        "rows_with_problems": problems,
        "unmapped_headers": list(unmapped),
    }


def _report(run: BankStatementImportRun, rows: list[ParsedRow]) -> ParseReport:
    counted = {status: 0 for status in ("valid", "warning", "invalid", "ignored_empty")}
    for row in rows:
        counted[row.status] = counted.get(row.status, 0) + 1
    return ParseReport(
        import_run_id=run.id,
        status=run.status,
        row_count=run.row_count or 0,
        valid=counted["valid"],
        warned=counted["warning"],
        invalid=counted["invalid"],
        ignored=counted["ignored_empty"],
    )
