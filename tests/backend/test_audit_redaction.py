"""Redaction has to be right at write time, because there is no second chance.

`audit_logs` grants the runtime role no UPDATE. A secret that reaches the column
stays there for the life of the row and of every backup taken since. So these
tests are about what never gets written, not about what a reader is shown.
"""

from __future__ import annotations

import pytest
from app.audit.redaction import (
    REDACTED,
    RedactionPolicy,
    is_prohibited_key,
    mask_iban_value,
    redact,
)

VISIBLE = RedactionPolicy(mask_iban=False)
MASKED = RedactionPolicy(mask_iban=True)


class TestAbsoluteProhibitions:
    """Settled by 04_Database_Schema.md:1470 — not policy, not parameterised."""

    @pytest.mark.parametrize(
        "key",
        [
            "password",
            "user_password",
            "passwd",
            "session_secret",
            "api_token",
            "refresh_token",
            "storage_credential",
            "private_key",
            "aws_access_key",
            "idempotency_key",
            "authorization",
            "cookie",
            "file_content",
        ],
    )
    def test_a_prohibited_key_never_carries_its_value(self, key: str) -> None:
        assert redact({key: "the-actual-secret"}, VISIBLE) == {key: REDACTED}

    def test_matching_is_case_insensitive(self) -> None:
        assert redact({"Authorization": "Bearer abc"}, VISIBLE) == {"Authorization": REDACTED}

    def test_prohibition_reaches_nested_structures(self) -> None:
        payload = {
            "request": {"headers": {"authorization": "Bearer abc"}, "path": "/api/v1/x"},
            "attempts": [{"token": "t1"}, {"token": "t2"}],
        }

        assert redact(payload, VISIBLE) == {
            "request": {"headers": {"authorization": REDACTED}, "path": "/api/v1/x"},
            "attempts": [{"token": REDACTED}, {"token": REDACTED}],
        }

    def test_a_digest_column_survives_although_its_name_contains_a_prohibited_word(
        self,
    ) -> None:
        """`idempotency_key_hash` exists so the raw key is never stored.

        Redacting it would remove the one safe identifier the row is allowed to
        keep, and the audit trail would lose the link to the idempotency record.
        """

        assert not is_prohibited_key("idempotency_key_hash")
        assert redact({"idempotency_key_hash": "a" * 64}, VISIBLE) == {
            "idempotency_key_hash": "a" * 64
        }

    def test_raw_bytes_are_replaced_by_their_shape(self) -> None:
        assert redact({"blob": b"1234567890"}, VISIBLE) == {"blob": f"{REDACTED} (10 bytes)"}

    def test_recursion_is_bounded(self) -> None:
        """A deep payload must be redacted, not crash the command writing it.

        Refusing at depth is the safe answer: the alternative is a RecursionError
        inside a transaction that was about to record what happened.
        """

        payload: dict[str, object] = {"leaf": "value"}
        for _ in range(40):
            payload = {"nested": payload}

        result = redact(payload, VISIBLE)

        flattened = repr(result)
        assert REDACTED in flattened
        assert "value" not in flattened


class TestIbanPolicy:
    """POL-003 is open, so the policy is supplied, never defaulted."""

    def test_masking_is_off_unless_the_caller_asks_for_it(self) -> None:
        payload = {"iban": "IR820540102680020817909002"}

        assert redact(payload, VISIBLE) == payload

    def test_masking_keeps_the_prefix_and_last_four(self) -> None:
        masked = mask_iban_value("IR820540102680020817909002")

        assert masked.startswith("IR82")
        assert masked.endswith("9002")
        assert "0540102680020817" not in masked

    def test_masking_applies_inside_free_text(self) -> None:
        """A reason field is where an IBAN turns up unannounced."""

        entry = {"reason": "Refund to IR820540102680020817909002 per ticket 41"}

        redacted = redact(entry, MASKED)

        assert "IR820540102680020817909002" not in redacted["reason"]
        assert "ticket 41" in redacted["reason"]

    def test_a_short_value_is_removed_rather_than_partially_shown(self) -> None:
        assert mask_iban_value("IR8205") == REDACTED


class TestShapePreservation:
    def test_strings_are_not_walked_character_by_character(self) -> None:
        """str is a Sequence; handling it after the Sequence branch would explode it."""

        assert redact({"name": "Golden"}, VISIBLE) == {"name": "Golden"}

    def test_non_string_scalars_pass_through(self) -> None:
        payload = {"count": 3, "ratio": 1.5, "ok": True, "missing": None}

        assert redact(payload, VISIBLE) == payload

    def test_the_original_is_not_mutated(self) -> None:
        """A command may still need the real values after writing audit."""

        original = {"password": "secret", "name": "Golden"}

        redact(original, VISIBLE)

        assert original["password"] == "secret"
