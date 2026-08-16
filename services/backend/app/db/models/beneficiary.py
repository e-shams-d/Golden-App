"""A reusable payment destination, owned by exactly one trader.

`04_Database_Schema.md:491-528`. The first table of M5, and the one every later
request row points at: a payment request names a beneficiary, and the revision it
submits copies that beneficiary's name and IBAN as they stood at that instant.

**No unique constraint on IBAN or on name may ever be added here.** Document 04
says it in terms — "Do not enforce a unique beneficiary per IBAN/name because
duplicates may be legitimate or incomplete. The service produces duplicate
warnings; it does not auto-merge" — and M2 wrote the prohibition down in
`app/db/models/bank.py` before this table existed, exporting
`IBAN_UNIQUE_IS_PERMITTED_ONLY_ON` so a test can assert it rather than trust a
comment. The same person may hold two accounts and two people may share a name. A
unique index would turn the approved warning into a refusal at data entry, and the
trader would meet it as an unexplained error while typing.

**`normalized_iban` is NOT NULL with a null-intolerant regex**, where
`bank_accounts.normalized_iban` is nullable with a null-tolerant one. M2 recorded
that asymmetry as a decision rather than an oversight and predicted this table's
form: a centre account may be registered before its IBAN is known, but a payment
destination without an IBAN cannot be paid.

**`status` carries the catalogue's four values; `verification_status` carries no
CHECK at all**, and the difference is not a matter of confidence. `beneficiary` is
an approved aggregate in `status_catalog.yaml` with exactly `active`, `inactive`,
`blocked` and `superseded`. There is no aggregate for the verification outcome —
document 04 names four values in a Notes cell and no approved catalogue covers
them. Enumerating them here would put a vocabulary into the database that the
governance layer has never approved, which is the failure `status_catalog.yaml`
exists to prevent. Recorded in `test_status_catalogue_drift.py`'s
`DELIBERATELY_UNCONSTRAINED` and raised as DOC-CONFLICT-048.

**No `deleted_at`.** A beneficiary that must stop being used becomes `inactive`,
`blocked` or `superseded`; the historical requests that reference it keep their own
snapshots and are unaffected by anything that happens here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    created_at_column,
    named_check,
    record_version_column,
    updated_at_column,
    uuid_primary_key,
)
from app.db.models.bank import IBAN_PATTERN

# The approved `beneficiary` aggregate, in the order document 06's machine moves
# through them. Kept as a tuple here and as SQL text in the migration;
# `tests/backend/test_status_catalogue_drift.py` compares this set against the
# catalogue and `tests/integration/test_schema_matches_models.py` compares the
# model against the database, so a drift between the three cannot hide.
BENEFICIARY_STATUSES: tuple[str, ...] = ("active", "inactive", "blocked", "superseded")

# Document 04 lists these in a Notes cell and no approved catalogue records them,
# so they are an application-level vocabulary rather than a CHECK. See the module
# docstring and DOC-CONFLICT-048.
VERIFICATION_STATUSES: tuple[str, ...] = ("not_checked", "verified", "mismatch", "failed")


class Beneficiary(Base):
    """A trader's payment destination. One trader, always, by foreign key."""

    __tablename__ = "beneficiaries"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    # The single owning edge. There is deliberately no second trader column, no
    # sharing table and no `is_shared` flag: DOC-CONFLICT-011's interim rule is
    # strict trader-owned isolation, and M5 builds no mechanism that could be
    # turned on later without a schema change and the review that comes with one.
    trader_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("traders.id"), nullable=False
    )

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Search and duplicate-detection helper, not an identity. Nullable because a
    # normalizer may have nothing to say about a name it cannot fold.
    normalized_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # What the trader typed, kept for display. `normalized_iban` is what anything
    # compares.
    iban: Mapped[str] = mapped_column(String(34), nullable=False)
    normalized_iban: Mapped[str] = mapped_column(String(26), nullable=False)

    bank_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("bank_profiles.id"), nullable=True
    )

    national_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)

    status: Mapped[str] = mapped_column(String(24), nullable=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Never trader-visible, named at the column so no serializer has to remember.
    notes_internal: Mapped[str | None] = mapped_column(Text, nullable=True)

    verification_status: Mapped[str] = mapped_column(String(24), nullable=False)
    verification_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check("length(btrim(full_name)) > 0", name="full_name_not_blank"),
        # Null-intolerant, unlike `bank_accounts`: the column is NOT NULL, so a
        # tolerant predicate would describe a state that cannot arise and would
        # read as though NULL were expected here too.
        named_check(f"normalized_iban ~ '{IBAN_PATTERN}'", name="normalized_iban_shape"),
        named_check(
            "status IN (" + ", ".join(f"'{value}'" for value in BENEFICIARY_STATUSES) + ")",
            name="status_value",
        ),
        # Doc 04:521-525 names both indexes. DOC-CONFLICT-042's approved rule is
        # that an index a document names keeps that name, written out rather than
        # left to the `ix_` convention.
        Index("idx_beneficiaries_trader_status", "trader_id", "status"),
        # Trader-scoped, not global. This is the index the duplicate warning reads,
        # and scoping it to the trader is the same isolation the foreign key states:
        # a lookup that could see another trader's row is one a bug could return.
        Index("idx_beneficiaries_normalized_iban", "trader_id", "normalized_iban"),
    )


__all__ = ["BENEFICIARY_STATUSES", "VERIFICATION_STATUSES", "Beneficiary"]
