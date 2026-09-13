"""The one statement file shape this platform expects, and the two ways it could stop being true.

M0 slice D. The owner decided on 2026-09-13 that the mapping is a single fixed function in code
rather than operator configuration: the file we expect is the input, and when the bank's real file
differs, the function changes.

That makes `app/statements/expected_file.py` the authority and the row `activate_version` writes its
consequence. Two failures follow, and each has a test here:

- the module could name a field the parser does not produce, which fails **every** import run at
  configuration time — after a person has uploaded a statement and pressed the button;
- the module and the row written from it could drift, which is the ordinary fate of a value written
  twice.

The second is checked against a database in
`tests/integration/test_bank_version_resolution.py::test_activation_gives_the_new_version_the_expected_statement_mapping`,
because it needs one. This file checks what can be checked without.

Covers: CI-STATEMENT-001.
"""

from __future__ import annotations

from app.statements.expected_file import (
    EXPECTED_CONFIG_HASH,
    EXPECTED_NORMALIZATION_RULES,
    EXPECTED_STATEMENT_MAPPING,
    EXPECTED_STATEMENT_TEMPLATE_VERSION,
)
from app.statements.parser import KNOWN_FIELDS, REQUIRED_FIELDS


def mapped_fields() -> set[str]:
    return {column["field"] for column in EXPECTED_STATEMENT_MAPPING["columns"]}


def test_the_expected_mapping_names_only_fields_the_parser_produces() -> None:
    """A name outside `KNOWN_FIELDS` is a configuration error that fails the run.

    **And it fails it late.** The parser refuses an unknown field before writing a row — which is
    the right behaviour, enforcement by absence rather than by escaping — but the refusal arrives
    after somebody has uploaded a statement and started an import. A typo here would make every
    import in the deployment fail identically, and the message would name a field rather than this
    file.
    """

    unknown = sorted(mapped_fields() - KNOWN_FIELDS)

    assert unknown == [], (
        f"the expected mapping names {unknown}, which the parser does not produce. Known fields: "
        f"{', '.join(sorted(KNOWN_FIELDS))}."
    )


def test_the_expected_mapping_carries_the_fields_matching_depends_on() -> None:
    """`REQUIRED_FIELDS` are the ones the fingerprint and the match index are built from.

    A mapping without them parses a file successfully and produces rows nothing can ever be matched
    against — the worst of the three outcomes, because it looks like it worked.
    """

    missing = sorted(REQUIRED_FIELDS - mapped_fields())

    assert missing == [], f"the expected mapping omits {missing}, so no row it produces can match"


def test_the_expected_mapping_reads_credit_and_debit_from_separate_columns() -> None:
    """§8.5: "Do not silently convert debit to credit or vice versa."

    The parser reads the two from separately mapped columns and never infers one from a sign, which
    is only a guarantee while the mapping actually supplies both. A file whose debits arrived as
    negative credits would be read as money received.
    """

    fields = mapped_fields()

    assert {"amount_in_irr", "amount_out_irr"} <= fields, (
        "the expected mapping does not name both directions, so a withdrawal could only be "
        "inferred from a sign — which §8.5 forbids in terms"
    )


def test_every_column_is_a_header_and_a_field_and_nothing_else() -> None:
    """The shape the parser reads, asserted so a fourth key cannot be added in the belief that
    something consumes it. `bank_mappings.mapping` is JSONB and will accept anything."""

    for column in EXPECTED_STATEMENT_MAPPING["columns"]:
        assert set(column) == {"header", "field"}, f"unexpected keys in {column}"
        assert isinstance(column["header"], str) and column["header"].strip()
        assert isinstance(column["field"], str) and column["field"].strip()


def test_no_header_is_used_twice() -> None:
    """Two columns claiming the same header is a mapping whose behaviour depends on which the
    parser reaches first. The fields differ, so it would not look like a duplicate."""

    headers = [column["header"] for column in EXPECTED_STATEMENT_MAPPING["columns"]]

    assert len(headers) == len(set(headers)), f"a header is mapped twice: {sorted(headers)}"


def test_the_config_hash_is_a_digest_of_what_it_describes() -> None:
    """`UNIQUE(bank_profile_version_id, file_type, config_hash)` makes this column load-bearing.

    A random value would let the same shape be inserted twice under one version, and two
    deployments running the same release would disagree — a diff between environments that looks
    like a real difference when nothing differs.

    Recomputed here rather than compared to a frozen literal: the mapping is *expected* to change
    when the bank's real file arrives, and a pinned digest would fail on the day that happens for
    no reason anybody could act on. What must hold is that the hash follows the content.
    """

    import hashlib
    import json

    expected = hashlib.sha256(
        json.dumps(
            {
                "mapping": EXPECTED_STATEMENT_MAPPING,
                "normalization_rules": EXPECTED_NORMALIZATION_RULES,
                "template_version": EXPECTED_STATEMENT_TEMPLATE_VERSION,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    assert expected == EXPECTED_CONFIG_HASH
    # `ck_bank_mappings_config_hash_is_hex` is M2's, and a value it refuses would fail the insert
    # during an activation rather than here.
    assert len(EXPECTED_CONFIG_HASH) == 64
    assert EXPECTED_CONFIG_HASH.lower() == EXPECTED_CONFIG_HASH


def test_persian_digits_are_folded_before_anything_is_parsed() -> None:
    """Iranian bank exports write numerals in Persian routinely.

    Without the fold, a date or an amount fails to parse — and §8.4 requires an unparseable field to
    be left null rather than guessed, so the row survives and says nothing. A statement that
    imported "successfully" with every amount null is the failure this rule prevents.
    """

    assert EXPECTED_NORMALIZATION_RULES.get("digits") == "fold_persian_to_ascii"
