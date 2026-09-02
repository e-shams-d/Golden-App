"""Duplicate detection over parsed statement rows.
`08_Bank_File_and_Result_Processing.md` §8.7.

M10 slice 4B. The whole section is nine lines and the last one governs everything above it:
**"A warning does not automatically delete or merge data."** So nothing here refuses a row,
removes a row or merges two — it marks and it reports, and a person decides.

§8.7 lists five signals and says they "may include", which is a menu rather than a mandate. Three
are implemented, and the choice is recorded rather than left to be inferred:

- **same normalized row fingerprint** — the obligation's own subject, `SVC-FINGERPRINT-001`;
- **same tracking/document number** — the signal an accountant actually uses, and the one that
  catches a bank re-sending a transfer with a different timestamp;
- **same original file checksum** — §26.2 names it as a test case, and slice 3 already records
  `source_hash` on every run, so the comparison costs nothing.

The two not implemented are **same bank account and statement period** — the period is optional
operator input, so absent on most uploads, and a signal that fires on `NULL = NULL` is a signal
that never fires — and **same timestamp, amount, and description**, which the fingerprint already
covers for every row where a timestamp exists.

**A reparse is not a duplicate, and that is the subtlety this module exists to get right.**
Document 08 §8.2 makes reprocessing the *specified* workflow: run 2 of a file reads the same bytes
and produces the same fingerprints as run 1, every single time. Comparing against every earlier row
would therefore flag every reparse completely, which would train an accountant to ignore the
warning — the worst outcome available. So rows of other runs **of the same statement file** are
excluded, and only rows from a different file count.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.bank_statement import (
    BankStatementFile,
    BankStatementImportRun,
    BankStatementRow,
)
from app.db.models.file_object import FileObject
from app.statements.parser import ParsedRow

# §8.6's state for a row a signal fired on. A *possible* duplicate: a bank statement legitimately
# contains two identical transfers, and this says "look at this", never "this is wrong".
ROW_POSSIBLE_DUPLICATE = "possible_duplicate"


@dataclass(frozen=True, slots=True)
class DuplicateFinding:
    """One row a signal fired on, and which signal."""

    row_number: int
    signal: str
    # What it collided with. A row id when the twin is stored, or the earlier row's number when the
    # twin is in this same parse and has no id yet.
    matched_row_id: uuid.UUID | None = None
    matched_row_number: int | None = None


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    findings: tuple[DuplicateFinding, ...] = ()
    # §8.7's first signal, which is about the file rather than any row: another statement file
    # already holds these exact bytes.
    duplicate_of_statement_file_id: uuid.UUID | None = None

    @property
    def flagged_rows(self) -> frozenset[int]:
        return frozenset(finding.row_number for finding in self.findings)


def find_duplicates(
    session: Session,
    *,
    run: BankStatementImportRun,
    statement: BankStatementFile,
    rows: tuple[ParsedRow, ...],
) -> DuplicateReport:
    """Every §8.7 signal this slice implements, over one parse's output.

    Read-only. Nothing is written here and nothing is refused; the caller marks the rows it is told
    about and opens one task for the run.
    """

    findings: list[DuplicateFinding] = []
    findings.extend(_within_this_parse(rows))
    findings.extend(_against_other_statements(session, statement=statement, rows=rows))
    del run

    return DuplicateReport(
        findings=tuple(findings),
        duplicate_of_statement_file_id=_a_file_with_the_same_bytes(session, statement),
    )


def _within_this_parse(rows: tuple[ParsedRow, ...]) -> list[DuplicateFinding]:
    """Two lines of one statement describing the same transfer.

    **The first occurrence is not flagged.** Only the later ones are: the row an accountant should
    look at is the repeat, and flagging both would double every finding and make the count
    meaningless.
    """

    findings: list[DuplicateFinding] = []
    seen_fingerprints: dict[str, int] = {}
    seen_tracking: dict[str, int] = {}

    for row in rows:
        if row.status == "ignored_empty":
            # A blank line has a fingerprint over its own position, so two of them never collide —
            # but skipping them here says so out loud rather than relying on that.
            continue

        first = seen_fingerprints.get(row.row_fingerprint)
        if first is not None:
            findings.append(
                DuplicateFinding(
                    row_number=row.row_number,
                    signal="same_normalized_fingerprint",
                    matched_row_number=first,
                )
            )
        else:
            seen_fingerprints[row.row_fingerprint] = row.row_number

        reference = row.tracking_number or row.document_number
        if not reference:
            continue
        earlier = seen_tracking.get(reference)
        if earlier is not None and first is None:
            # `first is None` so a row already flagged by fingerprint is not reported twice. Two
            # signals on one row is one row to look at.
            findings.append(
                DuplicateFinding(
                    row_number=row.row_number,
                    signal="same_tracking_or_document_number",
                    matched_row_number=earlier,
                )
            )
        elif earlier is None:
            seen_tracking[reference] = row.row_number

    return findings


def _against_other_statements(
    session: Session, *, statement: BankStatementFile, rows: tuple[ParsedRow, ...]
) -> list[DuplicateFinding]:
    """The same transfer already imported from a **different** statement file.

    The overlapping-period case, which is the one that actually happens: an operator uploads
    August, then uploads a July-to-August export, and the last week arrives twice.

    Rows of other runs of *this* file are excluded — see the module docstring. A reparse producing
    identical fingerprints is the specified workflow, not a finding.
    """

    fingerprints = {
        row.row_fingerprint: row.row_number for row in rows if row.status != "ignored_empty"
    }
    if not fingerprints:
        return []

    matches = session.execute(
        select(BankStatementRow.id, BankStatementRow.row_fingerprint)
        .join(
            BankStatementImportRun,
            BankStatementImportRun.id == BankStatementRow.bank_statement_import_run_id,
        )
        .where(BankStatementImportRun.bank_statement_file_id != statement.id)
        .where(BankStatementRow.row_fingerprint.in_(fingerprints.keys()))
    ).all()

    findings: list[DuplicateFinding] = []
    already: set[int] = set()
    for row_id, fingerprint in matches:
        row_number = fingerprints[fingerprint]
        if row_number in already:
            continue
        already.add(row_number)
        findings.append(
            DuplicateFinding(
                row_number=row_number,
                signal="same_fingerprint_in_another_statement",
                matched_row_id=row_id,
            )
        )
    return findings


def _a_file_with_the_same_bytes(
    session: Session, statement: BankStatementFile
) -> uuid.UUID | None:
    """§8.7's first signal: "same original file checksum".

    Compared over `file_objects.sha256_hash` rather than over the run's `source_hash`, so the
    answer holds for a statement nobody has parsed yet. Returns the earliest match, because the
    question an operator is being asked is "is this the same file you already uploaded?" and the
    useful answer names the original rather than an arbitrary one.
    """

    digest = session.scalar(
        select(FileObject.sha256_hash).where(FileObject.id == statement.original_file_id)
    )
    if not digest:
        return None

    return session.scalar(
        select(BankStatementFile.id)
        .join(FileObject, FileObject.id == BankStatementFile.original_file_id)
        .where(FileObject.sha256_hash == digest)
        .where(BankStatementFile.id != statement.id)
        .order_by(BankStatementFile.created_at.asc())
        .limit(1)
    )
