"""What `content_hash` is computed over, and what it deliberately ignores.

M5 slice 3, and this file exists because a negative control found nothing to catch
it. `UNIQUE(payment_request_id, content_hash)` is proved by
`tests/integration/test_request_revision_integrity.py` — but that test inserts rows
with hand-written hashes, so it never calls the function that produces them. Folding
`revision_number` into the digest makes every revision's hash unique, the constraint
then refuses nothing, and every test in the suite still passed.

That is the same shape as citing a line without reading it: the constraint was
verified and the input to the constraint was not. A uniqueness rule is only as strong
as the sameness it is given.

So this pins both halves. Identical submitted content must hash **the same** even when
the bookkeeping around it differs, and any change to what was submitted must hash
**differently**.

Covers: DB-REV-001.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from app.commands.payment_request import revision_content_hash
from app.db.models.payment_request import PaymentRequestRevision

REQUEST = uuid.uuid4()
BENEFICIARY = uuid.uuid4()
ATTACHMENT = uuid.uuid4()
IBAN = "IR060120000000000000000001"


def revision(**overrides: Any) -> PaymentRequestRevision:
    """A revision with plausible content, constructed but never persisted."""

    fields: dict[str, Any] = {
        "payment_request_id": REQUEST,
        "revision_number": 1,
        "beneficiary_id": BENEFICIARY,
        "beneficiary_name_snapshot": "Ali Example",
        "beneficiary_iban_snapshot": IBAN,
        "beneficiary_national_id_snapshot": None,
        "amount_irr": 5_000_000,
        "entered_amount_value": 500_000,
        "entered_amount_unit": "TOMAN",
        "description": "rent",
        "source_attachment_file_id": None,
        "created_by_actor_type": "trader_user",
        "created_by_actor_id": uuid.uuid4(),
    }
    fields.update(overrides)
    return PaymentRequestRevision(**fields)


# Fields that describe *when and by whom*, not *what was submitted*. Every one of
# these must leave the digest unchanged, or the uniqueness constraint stops refusing
# a correction that changes nothing.
BOOKKEEPING = [
    ("revision_number", 7),
    ("created_by_actor_type", "admin_user"),
    ("created_by_actor_id", uuid.uuid4()),
]

# Fields that *are* the submitted intent. Changing any one must change the digest, or
# a real correction would be refused as a duplicate.
CONTENT = [
    ("beneficiary_id", uuid.uuid4()),
    ("beneficiary_name_snapshot", "Someone Else"),
    ("beneficiary_iban_snapshot", "IR060120000000000000000002"),
    ("beneficiary_national_id_snapshot", "1234567890"),
    ("amount_irr", 6_000_000),
    ("entered_amount_value", 600_000),
    ("entered_amount_unit", "IRR"),
    ("description", "not rent"),
    ("source_attachment_file_id", ATTACHMENT),
]


def test_the_digest_is_sixty_four_characters() -> None:
    """The column is 64 wide, and `content_hash` carries a `v1:` prefix that makes it
    67. Using the wrong one truncates or fails at the insert."""

    digest = revision_content_hash(revision())
    assert len(digest) == 64
    assert not digest.startswith("v1:")


def test_identical_content_hashes_identically() -> None:
    """The half that keeps the uniqueness constraint meaningful."""

    assert revision_content_hash(revision()) == revision_content_hash(revision())


@pytest.mark.parametrize(("field", "value"), BOOKKEEPING, ids=[name for name, _ in BOOKKEEPING])
def test_bookkeeping_does_not_change_the_digest(field: str, value: Any) -> None:
    """The case the negative control found unguarded.

    `revision_number` is the dangerous one. Folding it in is the natural mistake —
    it *feels* like part of the revision — and it would make every digest unique, so
    `UNIQUE(payment_request_id, content_hash)` would accept everything while still
    existing. Nothing else in the suite would notice, because every other test
    supplies its own hash.
    """

    assert revision_content_hash(revision()) == revision_content_hash(
        revision(**{field: value})
    )


@pytest.mark.parametrize(("field", "value"), CONTENT, ids=[name for name, _ in CONTENT])
def test_every_content_field_changes_the_digest(field: str, value: Any) -> None:
    """The other direction, and it needs to be exhaustive.

    A field left out of the digest is a correction the database would refuse as a
    duplicate — the trader changes the IBAN, the hash does not move, and they are told
    nothing changed. Parametrised per field so the failure names which one.
    """

    assert revision_content_hash(revision()) != revision_content_hash(
        revision(**{field: value})
    )


def test_every_content_column_is_either_hashed_or_deliberately_excluded() -> None:
    """Guard the guard, and the reason this file is not just two tests.

    The two lists above are hand-written, so a column added to the table in a later
    slice would be in neither — and would be silently absent from the digest. This
    compares them against the model: every column is either exercised as content,
    listed as bookkeeping, or named in `EXCLUDED` with a reason.
    """

    excluded = {
        # Structural, not content. `payment_request_id` is what the uniqueness is
        # scoped *by*, so including it would be circular; `id` and `created_at` are
        # assigned by the database; `content_hash` is the output.
        "id",
        "payment_request_id",
        "created_at",
        "content_hash",
        # `revision_reason` is why a correction was made, not what was submitted. Two
        # revisions differing only in the reason are the same instruction to the bank,
        # and the reason is preserved on the row either way.
        "revision_reason",
        # Nothing in M5 writes it, and the migration grants no UPDATE. A digest over a
        # column that is always NULL would contribute nothing today and would change
        # every stored hash on the day it stopped being NULL.
        "superseded_at",
    }

    columns = set(PaymentRequestRevision.__table__.columns.keys())
    accounted = {name for name, _ in CONTENT} | {name for name, _ in BOOKKEEPING} | excluded

    assert columns - accounted == set(), (
        f"these revision columns are in neither list and neither excluded: "
        f"{sorted(columns - accounted)}. Each must be hashed as content, listed as "
        "bookkeeping, or excluded with a reason — a column in none of the three is "
        "one the digest silently ignores."
    )
    assert accounted - columns == set(), (
        f"these names no longer exist on the table: {sorted(accounted - columns)}"
    )
