"""What a trader is actually told, in the language they read and without a figure in it.

Two rules, one of which the module already stated and gated and the other of which it
broke in a product whose every other string is Persian.

**No figure.** `_message`'s docstring: *"No amount and no IBAN. A notification is
delivered outside the authenticated surface in every channel ADR-009 might eventually
choose, and a message that carries a figure is a figure on somebody's lock screen."*
`tests/integration/test_notification_projection.py` gates that for the attempt-failed
path. The gold-order path, added in a later slice, carried the confirmed total — and it
is the one branch of the projection with no test at all, which is how.

**Persian.** The audience is a goldsmith, not an operator. English here is not a rough
edge; it is unreadable by the person the message addresses.

Unit rather than integration because the content of a message is a pure function of the
row and the payload, and the sibling integration suite already proves the plumbing. The
payloads below deliberately carry the figures the bodies must not repeat — the
integration test records that its first version used a payload without them and therefore
could not have failed.

Covers: F-28, F-35.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from app.notifications.projection import _gold_order_message, _message

AMOUNT = 50_000_000_000
PERSIAN_LETTERS = set("ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهیآأإئء")


@dataclass
class _Order:
    id: uuid.UUID
    order_number: str
    trader_id: uuid.UUID


@dataclass
class _Request:
    id: uuid.UUID
    request_number: str


class _SessionReturning:
    """The two lines of `Session` this function uses."""

    def __init__(self, order: _Order | None) -> None:
        self._order = order

    def get(self, _model: Any, _identity: Any) -> _Order | None:
        return self._order


def _is_persian(text: str) -> bool:
    return any(character in PERSIAN_LETTERS for character in text)


ORDER = _Order(
    id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
    order_number="GS-5478d030",
    trader_id=uuid.UUID("00000000-0000-4000-8000-000000000002"),
)
REQUEST = _Request(
    id=uuid.UUID("00000000-0000-4000-8000-000000000003"),
    request_number="PR-2d60084a",
)


def _gold_order() -> tuple[str, str]:
    title, body, _entity, _entity_id, _trader = _gold_order_message(
        _SessionReturning(ORDER),
        {
            "gold_sale_order_id": str(ORDER.id),
            # Carried on purpose: a payload without it could not catch a body that repeats it.
            "confirmed_total_irr": str(AMOUNT),
        },
    )
    return title, body


def _payment(notification_type: str) -> tuple[str, str]:
    title, body, _entity, _entity_id = _message(
        notification_type,
        request=REQUEST,  # type: ignore[arg-type]
        payload={
            "publication_id": "00000000-0000-4000-8000-000000000004",
            "failure_code": "bank_rejected",
            "amount_irr": str(AMOUNT),
        },
    )
    return title, body


EVERY_MESSAGE = [
    ("gold order ready", _gold_order),
    ("result published", lambda: _payment("payment_result_published")),
    ("result corrected", lambda: _payment("payment_result_corrected")),
    ("attempt failed", lambda: _payment("payment_attempt_failed")),
]


@pytest.mark.parametrize(("name", "build"), EVERY_MESSAGE)
def test_the_message_is_written_in_persian(name: str, build: Any) -> None:
    title, body = build()
    assert _is_persian(title), f"{name}: the title is not Persian — {title!r}"
    assert _is_persian(body), f"{name}: the body is not Persian — {body!r}"


@pytest.mark.parametrize(("name", "build"), EVERY_MESSAGE)
def test_the_message_carries_no_figure(name: str, build: Any) -> None:
    """The rule `_message` states, applied to every branch rather than to one.

    Checked three ways because a body could repeat the figure in any of them: the plain
    integer, the grouped form a careless `format` produces, and the same digits in
    Persian, which is what a well-meaning localisation would reach for.
    """

    title, body = build()
    text = title + body
    plain = str(AMOUNT)
    grouped = f"{AMOUNT:,}"
    persian = plain.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    for spelling, what in ((plain, "plain"), (grouped, "grouped"), (persian, "Persian digits")):
        assert spelling not in text, f"{name}: the amount reached the body in its {what} form"


def test_the_identifiers_a_person_reads_out_stay_as_they_are() -> None:
    """Persian prose, ASCII identifiers.

    An order number is read down a telephone to somebody looking it up, and a failure code
    is quoted to support. Folding either into Persian digits would make the two sides of
    that conversation disagree — the same reason `normalize_username` leaves case to the
    column instead of lowering twice.
    """

    _title, body = _gold_order()
    assert ORDER.order_number in body

    _failed_title, failed_body = _payment("payment_attempt_failed")
    assert "bank_rejected" in failed_body
    assert REQUEST.request_number in failed_body
