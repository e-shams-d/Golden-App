"""A digest that still matches years later, computed by a different process.

The claim is not "stable within one run" — that is trivially true of anything. It
is that the same *meaning* produces the same digest across dict insertion orders,
Python hash randomisation, Unicode spellings and interpreter restarts.

So the subprocess test is the important one here. Everything else can pass while
`PYTHONHASHSEED` quietly participates in the result, and that failure appears
months later as an approved batch that will not export.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from app.core.hashing import (
    CANONICAL_HASH_VERSION,
    CanonicalisationError,
    canonical_bytes,
    content_hash,
    hashes_match,
    normalise_text,
    parameters_hash,
    unversioned_digest,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "services" / "backend"


class TestTheUnversionedDigest:
    """The bare form used by the two `CHAR(64)` bank columns.

    `bank_profile_versions.config_hash` and `bank_mappings.sample_header_hash` cannot
    hold the 67-character versioned string, so they store a bare digest — and lose
    the protection the `v1:` prefix provides. These tests are what replaces it: the
    output is pinned, so a change to `canonical_bytes` fails here instead of silently
    making every stored config hash stop matching a freshly computed one.
    """

    def test_the_digest_is_pinned_for_a_fixed_input(self) -> None:
        """The pin. If this fails, `canonical_bytes` changed and both bank columns
        need recomputing in a migration — which is the whole point of failing here."""

        assert unversioned_digest({"cutoff": "16:00", "limit": 1000}) == (
            "822a28ac31b38b11e2468ab897728d2a10465f2651f12f881c86454f0509123d"
        )

    def test_it_is_the_same_algorithm_as_the_versioned_form(self) -> None:
        """One serialiser, two renderings. A second implementation would let the two
        drift, and the drift would only show as a uniqueness that stopped working."""

        value = {"a": 1, "b": [2, 3]}

        assert content_hash(value) == f"{CANONICAL_HASH_VERSION}:{unversioned_digest(value)}"

    def test_it_fits_the_database_constraint(self) -> None:
        """`CHAR(64)` and `~ '^[0-9a-f]{64}$'`, checked here so a shape mismatch is a
        unit failure rather than an integrity error at insert time."""

        digest = unversioned_digest({"anything": True})

        assert len(digest) == 64
        assert digest == digest.lower()
        assert all(character in "0123456789abcdef" for character in digest)

    def test_key_order_still_does_not_matter(self) -> None:
        assert unversioned_digest({"a": 1, "b": 2}) == unversioned_digest({"b": 2, "a": 1})

    def test_it_refuses_what_the_versioned_form_refuses(self) -> None:
        """Same canonicalisation, so same refusals: a float cannot become a config
        hash any more than it can become a content hash."""

        with pytest.raises(CanonicalisationError):
            unversioned_digest({"limit": 1.5})


class TestDeterminism:
    def test_key_order_does_not_change_the_digest(self) -> None:
        """A parsed request body carries the sender's insertion order, not ours."""

        first = content_hash({"a": 1, "b": 2, "c": 3})
        second = content_hash({"c": 3, "b": 2, "a": 1})

        assert first == second

    def test_list_order_does_change_the_digest(self) -> None:
        """A list is ordered data. Reordering rows changes what a batch means."""

        assert content_hash([1, 2, 3]) != content_hash([3, 2, 1])

    def test_the_digest_survives_a_fresh_interpreter(self) -> None:
        """The test that matters, and the one an in-process check cannot make.

        `hash()` is randomised per process by PYTHONHASHSEED, so a digest that
        depended on it would be stable within a run and different tomorrow. Two
        subprocesses with different seeds must agree.
        """

        program = "\n".join(
            [
                f"import sys; sys.path.insert(0, {str(BACKEND_ROOT)!r})",
                "from app.core.hashing import content_hash",
                "print(content_hash({'name': 'gold centre', 'rows': [1, 2], 'when': None}))",
            ]
        )

        digests = set()
        for seed in ("0", "1", "12345"):
            result = subprocess.run(
                [sys.executable, "-c", program],
                capture_output=True,
                text=True,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin", "SYSTEMROOT": "C:\\Windows"},
                check=False,
            )
            assert result.returncode == 0, result.stderr
            digests.add(result.stdout.strip())

        assert len(digests) == 1, (
            f"the digest depends on PYTHONHASHSEED: {digests}. A stored hash "
            "would stop matching after a restart."
        )

    def test_the_digest_is_versioned(self) -> None:
        """A stored digest is compared against one computed by code that changed."""

        assert content_hash({"a": 1}).startswith(f"{CANONICAL_HASH_VERSION}:")

    def test_comparing_across_versions_raises_rather_than_returning_false(self) -> None:
        """False would read as "the content changed" and send someone looking for
        a difference that is not there."""

        with pytest.raises(ValueError, match="different algorithms"):
            hashes_match("v1:abc", "v2:abc")

    def test_matching_digests_compare_equal(self) -> None:
        digest = content_hash({"a": 1})

        assert hashes_match(digest, content_hash({"a": 1})) is True


class TestPersianNormalisation:
    def test_arabic_and_persian_yeh_hash_alike(self) -> None:
        """Both appear routinely in Iranian banking data for the same name."""

        assert content_hash("علي") == content_hash("علی")

    def test_arabic_and_persian_kaf_hash_alike(self) -> None:
        assert content_hash("ملك") == content_hash("ملک")

    def test_persian_digits_fold_to_ascii(self) -> None:
        assert normalise_text("۱۲۳") == "123"
        assert content_hash("۱۲۳") == content_hash("123")

    def test_zero_width_characters_are_stripped(self) -> None:
        """Invisible, meaningful for rendering, and present or absent by source."""

        assert content_hash("می‌رود") == content_hash("میرود")

    def test_whitespace_runs_collapse(self) -> None:
        assert content_hash("مرکز  طلا") == content_hash("مرکز طلا")

    def test_genuinely_different_text_still_differs(self) -> None:
        """Guard the guard: over-normalising would make every name equal."""

        assert content_hash("علی") != content_hash("رضا")


class TestRefusedInputs:
    @pytest.mark.parametrize("value", [1.5, 0.1, Decimal("1.5")])
    def test_floats_and_decimals_are_refused(self, value: object) -> None:
        """A float hashes to something stable and wrong: two amounts a human
        calls equal produce different digests."""

        with pytest.raises(CanonicalisationError):
            content_hash(value)

    def test_a_naive_datetime_is_refused(self) -> None:
        """It has no single instant, so two systems in different zones would hash
        the same wall clock differently."""

        with pytest.raises(CanonicalisationError, match="naive"):
            content_hash(datetime(2026, 8, 1, 12, 0))

    def test_an_unknown_type_is_refused_rather_than_stringified(self) -> None:
        """Falling back to str() makes the digest depend on __str__, which a
        library is free to change in a patch release."""

        class Opaque:
            pass

        with pytest.raises(CanonicalisationError, match="no canonical form"):
            content_hash(Opaque())


class TestTimestamps:
    def test_equal_instants_in_different_zones_hash_alike(self) -> None:
        tehran = timezone(timedelta(hours=3, minutes=30))
        same_moment_utc = datetime(2026, 8, 1, 8, 30, tzinfo=UTC)
        same_moment_tehran = datetime(2026, 8, 1, 12, 0, tzinfo=tehran)

        assert content_hash(same_moment_utc) == content_hash(same_moment_tehran)

    def test_microsecond_precision_is_always_rendered(self) -> None:
        """`isoformat()` omits microseconds when zero, so a value would hash
        differently depending on whether it round-tripped through the database."""

        without = datetime(2026, 8, 1, 12, 0, 0, 0, tzinfo=UTC)
        rendered = canonical_bytes(without).decode("utf-8")

        assert ".000000Z" in rendered


class TestStructuralSafety:
    def test_concatenation_cannot_collide(self) -> None:
        """Length-prefixed strings, so ("a","bc") and ("ab","c") differ."""

        assert content_hash(["a", "bc"]) != content_hash(["ab", "c"])

    def test_a_key_and_a_value_cannot_be_confused(self) -> None:
        assert content_hash({"a": "b"}) != content_hash({"b": "a"})

    def test_nested_structures_are_hashed_by_content(self) -> None:
        first = content_hash({"rows": [{"amount": 100}, {"amount": 200}]})
        second = content_hash({"rows": [{"amount": 100}, {"amount": 200}]})

        assert first == second

    def test_a_missing_element_changes_the_digest(self) -> None:
        """The property M7 depends on: omitting any element of a batch-version
        hash would let an approved digest match a materially different export."""

        complete = {
            "rows": [1, 2],
            "attempts": ["a"],
            "bank_profile_version": 3,
            "mapping_version": 1,
        }
        without_mapping = {
            key: value for key, value in complete.items() if key != "mapping_version"
        }

        assert content_hash(complete) != content_hash(without_mapping)


class TestParametersHash:
    def test_key_order_is_irrelevant_for_derivation_inputs(self) -> None:
        """Preferred to a unique index over raw JSONB, which would treat two
        orderings of the same derivation as different."""

        assert parameters_hash({"a": 1, "b": 2}) == parameters_hash({"b": 2, "a": 1})

    def test_different_parameters_differ(self) -> None:
        assert parameters_hash({"a": 1}) != parameters_hash({"a": 2})
