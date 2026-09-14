"""The one statement file shape this platform expects, as a function rather than as configuration.

**The owner's decision of 2026-09-13**, in their words: treat the mapping as a single fixed mapping
function — the file we expect *is* the input, no column conversion is needed — and when the real
file arrives, change the function at the code level.

That decision replaces a design this repository had been carrying without ever being able to use.
`bank_mappings.mapping` is operator-supplied configuration, and the two commands that would let an
operator supply it — `bank_mapping.create_version` and `bank_mapping.activate` — are catalogued and
**not served**. Worse, `bank_mapping.activate` carries `permission: []` with a `permission_gap`,
which is the same unanswered question `bank_profile.activate_version` carried until 2026-09-08. So
every import run required an `bank_mapping_id` that nothing but a seed could produce, and a
statement import screen would have been a surface for a flow that could not start.

**One mapping, in code, with the change point named.** `EXPECTED_STATEMENT_MAPPING` below is that
function's output. When the bank's real file turns out to differ, this file changes and nothing
else does: the parser stays pure and the command keeps taking a mapping. That is the seam the owner
asked for on 2026-09-08 — "a converter module maps the real input to the shape we expect, and that
module is separate precisely so the day the format changes, only it changes" — placed where it can
actually be exercised.

**Why this is not simply hard-coded inside the parser.** The parser is pure and takes a mapping as
an argument, which is what lets a mapping be tried against a real file in a unit test rather than
through a fixture chain. Collapsing the two would make "what shape do we expect" untestable except
by running an import. The mapping stays data; what this slice removes is the pretence that an
operator configures it.

**The headers are the bank's Persian column titles.** They are a guess until a real file arrives —
that is the whole point of the change point above — and they are written here rather than in a
migration so that a reader looking for "what do we expect the bank to send" finds prose next to it.

**One row per bank-profile version, written when that version is activated.**
`bank_mappings.bank_profile_version_id` is `NOT NULL` and `bank_statement.py` refuses a mapping
whose version is not the statement's, citing §8.2's "exact BankProfileVersion and BankMapping". A
single shared row would therefore belong to exactly one version — and `bankconfig/resolution.py`
retires the active version every time a new one is activated, which is an ordinary operation the
bank-configuration screen exists to perform. A centre that raised a transfer limit on Sunday would
find statement import broken on Monday, with a refusal naming a mapping id and no way to act on it.

**No migration seeds this, and that is ADR-007 rather than an oversight.** ADR-007 covers "initial
bank profiles, verified templates, mappings, limits, and source accounts", it is **open**, and its
safe default is synthetic fixtures only —
`test_bank_configuration.py::TestNothingIsSeeded` enforces both halves. A revision that planted a
row would be deciding an open ADR, which is the owner's to decide and not this module's. So the
writer is `activate_version`: the row appears as a consequence of an admin putting a configuration
into force, never in a database nobody has touched.

The consequence, stated rather than discovered: **a bank profile version activated before this
release has no statement mapping**, and no route creates a subsequent version to activate. No
database in existence is in that state — every one of them has no bank profile at all — but if one
ever is, seeding it is an owner decision under ADR-007, not a migration somebody adds quietly.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

EXPECTED_STATEMENT_TEMPLATE_VERSION: Final[int] = 1

# The columns, in the parser's vocabulary. Every `field` here is in `parser.KNOWN_FIELDS`; a name
# outside it is a configuration error that fails the run before a row is written, and
# `test_the_expected_mapping_names_only_fields_the_parser_produces` is what stops this file
# introducing one.
#
# `transaction_date` and `amount_in_irr` are `parser.REQUIRED_FIELDS` — the three the fingerprint
# and the match index are built from. A mapping without them describes a file nothing can be
# matched against.
EXPECTED_STATEMENT_MAPPING: Final[dict[str, Any]] = {
    "columns": [
        {"header": "تاریخ", "field": "transaction_date"},
        {"header": "ساعت", "field": "transaction_time"},
        {"header": "بستانکار", "field": "amount_in_irr"},
        {"header": "بدهکار", "field": "amount_out_irr"},
        {"header": "مانده", "field": "balance_irr"},
        {"header": "شماره سند", "field": "document_number"},
        {"header": "شماره پیگیری", "field": "tracking_number"},
        {"header": "شرح", "field": "description"},
        {"header": "نام طرف حساب", "field": "counterparty_name"},
        {"header": "شماره حساب طرف", "field": "counterparty_account"},
        {"header": "شبا طرف حساب", "field": "counterparty_iban"},
    ]
}

# Persian digits folded to ASCII before anything is parsed. Iranian bank exports write numerals in
# Persian routinely, and a date or an amount that failed to parse for that reason would be recorded
# as unparseable — which §8.4 requires be left null rather than guessed, so the row would survive
# and say nothing.
EXPECTED_NORMALIZATION_RULES: Final[dict[str, Any]] = {"digits": "fold_persian_to_ascii"}

# `bank_mappings.config_hash` is `NOT NULL` and M2's vocabulary for "this exact configuration".
#
# **A digest of the mapping, not a random value.** Two deployments running the same release hold the
# same hash, so a diff between environments is a real difference rather than noise — and
# `UNIQUE(bank_profile_version_id, file_type, config_hash)` means a per-row random value would let
# the same shape be inserted twice under one version.
EXPECTED_CONFIG_HASH: Final[str] = hashlib.sha256(
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
