"""The eight comparisons `15_Agent_Implementation_Plan.md` §15.5 lists, as one pure function.

M7 slice 3. §15.5 gives eight equalities and says a mismatch "quarantines the export and creates a
high-priority task/security event". This module is only the comparing; quarantining is the
caller's, because it writes.

**Pure, and that is not a style preference.** Two of the eight cannot fail through the database at
all: `fk_export_approval_same_version` makes it impossible for a stored export to cite an approval
of another version, and `ck_batch_approvals_decision_shape` plus
`fk_batch_approvals_approved_hash` make it impossible for a stored approval to name a hash its
version does not have. A test that could only reach these checks through PostgreSQL could
therefore never provoke them — it would assert that the code runs eight comparisons by exercising
six. Taking values rather than rows means each of the eight has a failing case that can actually
be written.

**Eight named failures, not a boolean.** `SVC-INTEGRITY-001` requires each comparison to have its
own failing case, and M6's lesson is why: a single `integrity_holds` assertion passes with seven
of the eight comparisons deleted. Returning *which* comparison failed also gives the security
event something to say beyond "something was wrong", which is the difference between an operator
who can act and one who opens a ticket.

**Nothing here is a tolerance.** `04_Database_Schema.md:171` — "Exact equality is required" — and
every value compared is an integer, a UUID or a lowercase hex digest. There is no rounding, no
normalisation and no case folding, because each of those is a place where two different things
could be called equal.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class IntegrityCheck(StrEnum):
    """The eight, named as §15.5 words them.

    A `StrEnum` so the value reaches an audit row and a security event unchanged: an operator
    reading `export_content_hash_matches_version` learns which equality failed without holding
    this file open, and a later reader can group failures by kind.
    """

    EXPORT_VERSION_IS_THE_APPROVED_VERSION = "export_version_is_the_approved_version"
    EXPORT_CONTENT_HASH_MATCHES_VERSION = "export_content_hash_matches_version"
    APPROVAL_HASH_MATCHES_VERSION = "approval_hash_matches_version"
    EXPORT_TOTAL_MATCHES_VERSION = "export_total_matches_version"
    EXPORT_ROW_COUNT_MATCHES_VERSION = "export_row_count_matches_version"
    MAPPING_MATCHES_APPROVED_MAPPING = "mapping_matches_approved_mapping"
    SOURCE_ACCOUNT_MATCHES_APPROVED_ACCOUNT = "source_account_matches_approved_account"
    FILE_CHECKSUM_MATCHES_STORED_CHECKSUM = "file_checksum_matches_stored_checksum"


@dataclass(frozen=True, slots=True)
class IntegrityFacts:
    """Everything the eight comparisons need, read once by the caller.

    Deliberately flat and deliberately not ORM rows. A function that took `export`, `version` and
    `approval` objects would be one lazy-load away from comparing a value it fetched at comparison
    time against one fetched earlier — and the whole point of these checks is that they compare
    what was *recorded*.
    """

    # What the export row claims.
    export_version_id: uuid.UUID
    export_content_hash: str
    export_total_amount_irr: int
    export_row_count: int
    export_bank_mapping_id: uuid.UUID
    export_bank_account_id: uuid.UUID
    export_file_sha256_hash: str

    # What the version holds. The version is immutable, so these are what a manager approved.
    version_id: uuid.UUID
    version_content_hash: str
    version_total_amount_irr: int
    version_row_count: int
    version_bank_mapping_id: uuid.UUID
    version_bank_account_id: uuid.UUID

    # What the approval recorded.
    approval_version_id: uuid.UUID
    approval_content_hash: str

    # What the bytes on disk hash to **now**, measured at check time rather than read from the
    # row. §15.5's eighth comparison is the only one whose left side is not a stored value, and
    # that is its entire purpose: it detects a file that changed after it was recorded.
    measured_file_sha256_hash: str


@dataclass(frozen=True, slots=True)
class IntegrityFailure:
    check: IntegrityCheck
    expected: str
    actual: str

    def describe(self) -> str:
        return f"{self.check.value}: expected {self.expected}, found {self.actual}"


def failed_checks(facts: IntegrityFacts) -> tuple[IntegrityFailure, ...]:
    """Every comparison that does not hold, in §15.5's order.

    **All eight are evaluated, not short-circuited.** Returning on the first failure would make
    the security event describe one symptom of what may be several, and an operator investigating
    a quarantined export needs the whole picture — a file whose hash, total and row count all
    disagree is a different incident from one whose checksum alone moved.
    """

    comparisons: Sequence[tuple[IntegrityCheck, object, object]] = (
        # `export version == approved version`. Unfailable for a stored row —
        # `fk_export_approval_same_version` refuses the pair — and checked anyway, because §15.5
        # lists it and because the constraint protects the table, not this function's callers.
        (
            IntegrityCheck.EXPORT_VERSION_IS_THE_APPROVED_VERSION,
            facts.approval_version_id,
            facts.export_version_id,
        ),
        # `export content hash == batch-version hash`. The file renders what the version says.
        (
            IntegrityCheck.EXPORT_CONTENT_HASH_MATCHES_VERSION,
            facts.version_content_hash,
            facts.export_content_hash,
        ),
        # `approval hash == batch-version hash`. The manager approved what the version says. With
        # the one above, this is the whole chain: manager → content → file.
        (
            IntegrityCheck.APPROVAL_HASH_MATCHES_VERSION,
            facts.version_content_hash,
            facts.approval_content_hash,
        ),
        (
            IntegrityCheck.EXPORT_TOTAL_MATCHES_VERSION,
            facts.version_total_amount_irr,
            facts.export_total_amount_irr,
        ),
        (
            IntegrityCheck.EXPORT_ROW_COUNT_MATCHES_VERSION,
            facts.version_row_count,
            facts.export_row_count,
        ),
        # `mapping version == approved mapping version` and `source account == approved source
        # account`. The approval row stores neither — the *version* does, and the approval is
        # bound to the version by hash — so the comparison is export against version. A mapping
        # that changed between approval and generation produces a file laid out differently from
        # the one that was reviewed; a source account that changed sends the money from
        # somewhere else.
        (
            IntegrityCheck.MAPPING_MATCHES_APPROVED_MAPPING,
            facts.version_bank_mapping_id,
            facts.export_bank_mapping_id,
        ),
        (
            IntegrityCheck.SOURCE_ACCOUNT_MATCHES_APPROVED_ACCOUNT,
            facts.version_bank_account_id,
            facts.export_bank_account_id,
        ),
        # `actual file checksum == stored checksum`. The only one that touches the world rather
        # than the database, and the only one that can catch a file edited in place.
        (
            IntegrityCheck.FILE_CHECKSUM_MATCHES_STORED_CHECKSUM,
            facts.export_file_sha256_hash,
            facts.measured_file_sha256_hash,
        ),
    )

    return tuple(
        IntegrityFailure(check=check, expected=str(expected), actual=str(actual))
        for check, expected, actual in comparisons
        if expected != actual
    )


def holds(facts: IntegrityFacts) -> bool:
    """Convenience for a caller that only needs the verdict.

    Provided because the alternative is every caller writing `not failed_checks(...)`, and one of
    them eventually writing `failed_checks(...) is None` — which is always false and always
    passes.
    """

    return not failed_checks(facts)
