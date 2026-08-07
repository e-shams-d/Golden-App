"""A mapping value must never become a SQL identifier on trust.

`bank_mappings.mapping` is operator-supplied JSONB, and the import/export code M4
onwards will write has to turn parts of it into column references. Values can be
parameterised; identifiers cannot, so the only defence is an allowlist — and the
first importer written must find one already here rather than solving it inline.

The injection fixture is the point of `BANK_A_MAPPING_INVALID`: a real mapping-shaped
payload carrying a field name that would end a quoted identifier and start a new
statement. The resolver must refuse it, not quote it.
"""

from __future__ import annotations

import pytest
from app.banking.mapping_identifiers import (
    UnsafeIdentifierError,
    resolve_all,
    resolve_identifier,
)
from bank_fixtures import MAPPINGS_BY_NAME, SYNTHETIC_ALLOWED_IDENTIFIERS

ALLOWED = SYNTHETIC_ALLOWED_IDENTIFIERS


class TestTheAllowlistGate:
    def test_an_allowlisted_identifier_is_returned_unchanged(self) -> None:
        assert resolve_identifier("iban", allowed=ALLOWED) == "iban"

    def test_an_identifier_outside_the_allowlist_is_refused(self) -> None:
        """Not "unknown so ignored" and not "unknown so quoted" — refused."""

        with pytest.raises(UnsafeIdentifierError, match="not an allowlisted identifier"):
            resolve_identifier("password_hash", allowed=ALLOWED)

    def test_an_empty_allowlist_refuses_everything(self) -> None:
        """An empty allowlist usually means configuration failed to load.

        Falling back to "permit anything" at that moment is how a misconfiguration
        becomes an injection.
        """

        with pytest.raises(UnsafeIdentifierError, match="allowlist is empty"):
            resolve_identifier("iban", allowed=frozenset())


class TestTheShapeGate:
    @pytest.mark.parametrize(
        "candidate",
        [
            'amount_irr"; DROP TABLE bank_mappings; --',
            "amount_irr; SELECT 1",
            "AMOUNT_IRR",
            "amount irr",
            "1amount",
            "",
            "a" * 64,
            "amount_irr--",
            'iban"',
        ],
    )
    def test_an_unsafe_shape_is_refused_even_when_allowlisted(self, candidate: str) -> None:
        """The second gate, tested with the value *in* the allowlist.

        This is the case that matters: an allowlist assembled from configuration —
        which is what a bank profile is — can be widened by accident, and one
        mistake must not be sufficient. So the shape check runs on the allowlisted
        value rather than instead of the membership test.
        """

        with pytest.raises(UnsafeIdentifierError):
            resolve_identifier(candidate, allowed=frozenset({candidate}))

    def test_the_shape_gate_message_blames_the_allowlist(self) -> None:
        """Because it is the allowlist that is wrong, and the message decides where
        the next person looks."""

        with pytest.raises(UnsafeIdentifierError, match="allowlist itself is wrong"):
            resolve_identifier("Bad Name", allowed=frozenset({"Bad Name"}))


class TestNonStringValues:
    @pytest.mark.parametrize("candidate", [1, None, 1.5, ["iban"], {"field": "iban"}, True])
    def test_a_non_string_is_refused_rather_than_coerced(self, candidate: object) -> None:
        """Mapping values come from JSONB, so any JSON type can arrive.

        `str(candidate)` would turn `None` into the identifier `None` and a list into
        something with brackets in it.
        """

        with pytest.raises(UnsafeIdentifierError, match="must be a string"):
            resolve_identifier(candidate, allowed=ALLOWED)


class TestResolvingASet:
    def test_a_valid_list_resolves_in_order(self) -> None:
        assert resolve_all(["iban", "amount_irr"], allowed=ALLOWED) == ("iban", "amount_irr")

    def test_one_bad_identifier_refuses_the_whole_set(self) -> None:
        """All or nothing. A partially resolved mapping silently omits a column, and
        an export missing a field is worse than an export that did not run."""

        with pytest.raises(UnsafeIdentifierError):
            resolve_all(["iban", "not_allowlisted"], allowed=ALLOWED)

    def test_a_non_sequence_is_refused(self) -> None:
        with pytest.raises(UnsafeIdentifierError, match="expected a list"):
            resolve_all("iban", allowed=ALLOWED)


class TestAgainstTheRealFixtures:
    def test_every_field_in_the_valid_mappings_resolves(self) -> None:
        """Guard the guard: if the allowlist did not cover the synthetic mappings,
        every refusal test above would pass for the wrong reason."""

        for name in ("BANK_A_MAPPING_V1", "BANK_A_MAPPING_V2"):
            fields = [column["field"] for column in MAPPINGS_BY_NAME[name].mapping["columns"]]

            assert resolve_all(fields, allowed=SYNTHETIC_ALLOWED_IDENTIFIERS) == tuple(fields)

    def test_the_invalid_fixture_is_refused(self) -> None:
        """`BANK_A_MAPPING_INVALID` exists so the allowlist has something real to
        refuse rather than a string invented inside a test."""

        fixture = MAPPINGS_BY_NAME["BANK_A_MAPPING_INVALID"]
        fields = [column["field"] for column in fixture.mapping["columns"]]

        assert fixture.is_invalid is True
        with pytest.raises(UnsafeIdentifierError):
            resolve_all(fields, allowed=SYNTHETIC_ALLOWED_IDENTIFIERS)

    def test_the_injection_payload_would_be_refused_even_if_allowlisted(self) -> None:
        """Both gates, on the real payload."""

        fixture = MAPPINGS_BY_NAME["BANK_A_MAPPING_INVALID"]
        payload = fixture.mapping["columns"][1]["field"]

        assert "DROP TABLE" in payload
        with pytest.raises(UnsafeIdentifierError):
            resolve_identifier(payload, allowed=frozenset({payload}))
