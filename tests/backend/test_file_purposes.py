"""The upload vocabulary, checked against the documents that define it.

Covers: FILE-PURPOSE-001, FILE-PURPOSE-002, FILE-PURPOSE-003, SEC-PURPOSE-001,
OPS-LIMIT-001.

Every assertion here derives its expectation from a gated artifact — the API
specification for the purpose set, `app/storage/keys.py` for the key pattern, the
catalogue itself for the rest — rather than restating a value. A test that restates the
seven purposes is a second copy of the list, and the whole reason this catalogue exists
in governance is that a second copy is a second thing to drift.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from app.files.purposes import (
    PURPOSES,
    VISIBILITY_SCOPES,
    UnknownFilePurposeError,
    accepts,
    purpose_ids,
    resolve,
    size_limit,
    visibility_scope,
)
from app.storage.keys import InvalidStorageCategoryError, generate_storage_key
from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPOSITORY_ROOT
    / "Implementation Docs"
    / "02_Architecture_and_Contracts"
    / "05_API_Specification.md"
)
CATALOG = REPOSITORY_ROOT / "docs" / "governance" / "file_purpose_catalog.yaml"


def purposes_stated_by_the_specification() -> list[str]:
    """Parse `05_API_Specification.md` §14.2's allowed Phase 1A purposes.

    The block is a fenced `text` list introduced by "Allowed Phase 1A purposes:". Parsed
    rather than quoted so that a purpose added to or removed from the contract fails this
    file on the day it changes.
    """

    lines = SPEC.read_text(encoding="utf-8").splitlines()
    heading = next(
        (
            number
            for number, line in enumerate(lines)
            if line.strip().startswith("Allowed Phase 1A purposes")
        ),
        None,
    )
    if heading is None:  # the guard below turns this into a readable failure
        return []

    fence = heading + 1
    while fence < len(lines) and not lines[fence].startswith("```"):
        fence += 1

    found: list[str] = []
    for line in lines[fence + 1 :]:
        if line.startswith("```"):
            break
        if line.strip():
            found.append(line.strip())
    return found


def _catalogue() -> list[dict]:
    """The governance catalogue's entries, as written."""

    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))["purposes"]


def _catalogued_ids() -> list[str]:
    return [entry["id"] for entry in _catalogue()]


def test_the_specification_still_states_a_purpose_list() -> None:
    """Guard the guard.

    `test_the_catalogue_matches_the_specification` compares two lists. If the parser
    stops finding the block — a renamed heading, a changed fence — it returns an empty
    list and the comparison would fail loudly rather than pass, but only because the
    catalogue is non-empty. This asserts the parser's own output directly so the reason
    for a failure is never ambiguous.
    """

    stated = purposes_stated_by_the_specification()
    assert len(stated) >= 5, (
        f"parsed only {stated} from {SPEC.name} §14.2 — the block's heading or fence "
        "changed and the comparison below is no longer reading the contract"
    )


def test_the_catalogue_matches_the_specification() -> None:
    """FILE-PURPOSE-001.

    The governance catalogue is not allowed to invent a purpose the contract does not
    offer, and is not allowed to omit one it does. Both directions, because omitting is
    the quieter failure: an upload purpose nothing accepts looks like a client bug.

    Reads the **YAML**, not the inlined copy. The first version of this read
    `purpose_ids()`, which meant it proved `spec == inlined` and said nothing about the
    file it names — dropping a purpose from governance left it green. That was found by
    the negative control, not by reading it: the sabotage edited the YAML and this test
    passed. The three links are now each asserted against the artifact they are about.
    """

    assert _catalogued_ids() == purposes_stated_by_the_specification()


def test_the_inlined_copy_matches_the_catalogue() -> None:
    """The middle link. `docs/` is not in the runtime image, so the purposes are inlined
    in `app/files/purposes.py` — the same arrangement as the permission catalogue, and
    for the same reason. This is what keeps the copy honest.

    Every field is compared, not just the ids: a limit or an accepted type that drifted
    would be a runtime that accepts something governance does not, which is worse than a
    missing purpose because nothing would look wrong.
    """

    document = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    governed = {entry["id"]: entry for entry in document["purposes"]}

    assert list(governed) == list(purpose_ids()), (
        "the inlined purpose list and the governance catalogue disagree. "
        f"catalogue: {list(governed)}; inlined: {list(purpose_ids())}"
    )

    for identifier, entry in governed.items():
        inlined = PURPOSES[identifier]
        assert inlined.visibility_scope == entry["visibility_scope"], identifier
        assert inlined.accepted_media_types == frozenset(entry["accepted_media_types"]), identifier
        assert inlined.accepted_extensions == frozenset(entry["accepted_extensions"]), identifier
        assert inlined.max_bytes_development_only == entry["max_bytes_development_only"], identifier
        assert inlined.limits_status == entry["limits_status"], identifier


def test_the_catalogue_is_not_empty() -> None:
    """Guard the guard: two empty collections are equal, and the comparison above would
    pass against a catalogue whose `purposes:` key had been emptied."""

    assert len(PURPOSES) >= 5


def test_every_purpose_is_usable_as_a_storage_key_segment() -> None:
    """FILE-PURPOSE-002.

    The purpose becomes the first path segment of the storage key, so it is constrained
    rather than trusted. The pattern is taken from the module that enforces it instead of
    being written out again here.
    """

    for identifier in purpose_ids():
        key = generate_storage_key(category=identifier, moment=_moment())
        assert key.startswith(f"{identifier}/")


def test_the_key_builder_still_rejects_a_bad_category() -> None:
    """Guard the guard for FILE-PURPOSE-002.

    The test above passes vacuously if `generate_storage_key` stops validating — a
    pattern loosened to `.*` would accept every purpose and every traversal attempt
    alike. This asserts the guard it depends on is still a guard.
    """

    for bad in ("../etc", "Payment_Request", "payment request", "", "9lives"):
        with pytest.raises(InvalidStorageCategoryError):
            generate_storage_key(category=bad, moment=_moment())


def test_visibility_scope_is_a_closed_set() -> None:
    """FILE-PURPOSE-003.

    Two values, and adding a third to the catalogue is a new access rule that the
    ownership resolver has to be taught — not a wider column. The loader refuses it, so
    the failure arrives at import rather than at a download.
    """

    for identifier in purpose_ids():
        assert visibility_scope(identifier) in VISIBILITY_SCOPES

    document = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    declared = document["metadata"]["visibility_values"]
    assert tuple(declared) == VISIBILITY_SCOPES, (
        "the catalogue's declared visibility values and the tuple the code is written "
        "against have diverged"
    )


def test_a_third_visibility_scope_is_refused_by_the_constructor() -> None:
    """Guard the guard for FILE-PURPOSE-003: the closed set is enforced, not described."""

    from app.files.purposes import _purpose

    with pytest.raises(ValueError, match="visibility_scope"):
        _purpose(
            "misc_internal",
            visibility_scope="public",
            media_types=("application/pdf",),
            extensions=("pdf",),
            max_bytes=1,
        )


def test_an_unknown_purpose_is_refused_rather_than_defaulted() -> None:
    """SEC-PURPOSE-001.

    The refusal is the default branch. A file service that answers "no rule, so allow"
    accepts content under a category nobody enumerated, into a key namespace nobody
    bounded.
    """

    for unknown in ("", "payment", "Payment_Request_Source", "../misc_internal"):
        with pytest.raises(UnknownFilePurposeError):
            resolve(unknown)
        with pytest.raises(UnknownFilePurposeError):
            accepts(unknown, "application/pdf")
        with pytest.raises(UnknownFilePurposeError):
            size_limit(unknown)


def test_a_known_purpose_refuses_a_type_it_does_not_list() -> None:
    """SEC-PURPOSE-001, the other half: acceptance is per purpose, not global.

    A bank statement is a spreadsheet and a receipt is an image. A service that accepted
    any catalogued type for any purpose would let an executable-bearing spreadsheet in
    wherever an image was expected.
    """

    assert accepts("bank_statement", "text/csv")
    assert not accepts("bank_statement", "image/jpeg")
    assert accepts("incoming_payment_receipt", "image/jpeg")
    assert not accepts("incoming_payment_receipt", "text/csv")


def test_every_entry_is_marked_blocked_by_the_open_policy() -> None:
    """OPS-LIMIT-001, first half.

    Per entry rather than as a header note, because a header note is a thing one entry
    can quietly escape.

    Reads the **YAML**, where the marker is a declaration somebody can edit. On the
    inlined side `limits_status` is a dataclass default, so asserting it there was very
    nearly vacuous — it could not have differed. Found by the negative control: editing
    an entry's marker to `approved` left this green.
    """

    for entry in _catalogue():
        assert entry["limits_status"] == "blocked_by_POL_006", (
            f"{entry['id']} no longer records that its limits are unapproved. POL-006 is "
            "open; a limit that stops saying so is a guessed production value"
        )


def test_production_refuses_to_start_on_unapproved_limits(settings_factory) -> None:
    """OPS-LIMIT-001, second half — the marker is load-bearing.

    Without this, `blocked_by_POL_006` is a comment. The refusal is what turns the open
    decision into something a deployment cannot walk past.

    Built through `settings_factory`, which supplies every *other* production
    requirement — including this flag, so the rest of the suite is unaffected. Overriding
    it to False here is what makes this test about POL-006 and not about a missing
    release commit: if it raised for another reason it would pass while proving nothing.
    """

    with pytest.raises(ValidationError, match="FILE_UPLOAD_LIMITS_ARE_PRODUCTION_APPROVED"):
        settings_factory(app_env="production", file_upload_limits_are_production_approved=False)

    approved = settings_factory(
        app_env="production", file_upload_limits_are_production_approved=True
    )
    assert approved.file_upload_limits_are_production_approved is True


def test_the_limits_rule_does_not_fire_outside_production(settings_factory) -> None:
    """The other direction. A refusal that also blocked local development would be
    removed within a week, and then production would be unguarded too."""

    for environment in ("local", "test", "staging"):
        assert (
            settings_factory(
                app_env=environment, file_upload_limits_are_production_approved=False
            )
            is not None
        )


def test_the_limits_are_not_approved_by_default() -> None:
    """The direction that matters: nobody inherits approval by deploying.

    Read off the field rather than off a constructed Settings, because the test fixture
    deliberately supplies the flag and would hide a changed default.
    """

    from app.core.config import Settings

    assert Settings.model_fields["file_upload_limits_are_production_approved"].default is False


def _moment() -> datetime:
    return datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
