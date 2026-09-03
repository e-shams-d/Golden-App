"""Names stay behind one indirection, and the five statuses become typed errors.

Every name in `audit_outbox_catalog.yaml` is marked
`provisional_pending_m0_approval`. They will be renamed. These tests keep the
indirection honest so the rename stays a one-line edit rather than a call-site
sweep plus a migration.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest
from app.audit.registry import ALL_COMMAND_NAMES, RENAME_CENTER_PROFILE, CommandNames
from app.core.errors import (
    AppError,
    BusinessRuleViolationError,
    IdempotencyKeyReusedError,
    InvalidStateTransitionError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)

# Resolved from this test file, not from inside the package. The application must
# never read a repository document — it is not shipped in the container image, and
# the path arithmetic that reaches it is only valid in a source checkout.
CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "governance" / "audit_outbox_catalog.yaml"
)


@lru_cache(maxsize=1)
def catalog() -> dict[str, object]:
    loaded: object = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{CATALOG_PATH} does not contain a mapping"
    return {str(key): value for key, value in loaded.items()}


def catalogued_audit_actions() -> frozenset[str]:
    actions = catalog()["audit_actions"]
    assert isinstance(actions, list)
    return frozenset(str(action) for action in actions)


def command_catalog() -> dict:
    """`command_catalog.yaml`, which is JSON in a .yaml file like its neighbours."""

    import json

    path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "governance"
        / "command_catalog.yaml"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def catalogued_outbox_events() -> frozenset[str]:
    events = catalog()["outbox_events"]
    assert isinstance(events, list)
    return frozenset(str(event) for event in events)


class TestNameRegistry:
    def test_a_catalogued_name_really_is_in_the_catalogue(self) -> None:
        """The claim is checked against the file, not taken on trust."""

        catalogued_actions = catalogued_audit_actions()
        catalogued_events = catalogued_outbox_events()

        for names in ALL_COMMAND_NAMES:
            if not names.catalogued:
                continue
            assert names.audit_action in catalogued_actions, (
                f"{names.audit_action!r} claims to be catalogued and is not"
            )
            if names.outbox_event_type is not None:
                assert names.outbox_event_type in catalogued_events

    def test_a_command_row_that_names_an_event_has_one_declared(self) -> None:
        """The other direction, and the direction that was missing.

        The test above asks "is the event you declared real?". Nothing asked "did you declare the
        event the catalogue asks for?", and the difference is not academic: **M10 slice 6 shipped
        without one and merged green.** `command_catalog.yaml`'s `incoming_payment.confirm` row
        carries `outbox_event: GoldOrderReadyForDispatch`; `CONFIRM_INCOMING_PAYMENT` was written
        with `outbox_event_type=None` and a comment asserting the catalogue gave it null. The
        comment was wrong — it had been checked against `audit_outbox_catalog.yaml`'s action list
        rather than against the command row — and no gate could tell.

        A missing event is silent in a way a wrong one is not: nothing downstream fires, no
        notification is sent, and every test passes because nothing was asked to observe an
        absence.

        Matched on the **audit action**, which is the one field both files agree on. Command rows
        are keyed by an `id` that is not the audit action and not the route, so joining on the
        action is what makes the two comparable without a hand-maintained mapping.
        """

        commands = command_catalog()["commands"]
        declared = {
            names.audit_action: names.outbox_event_type for names in ALL_COMMAND_NAMES
        }

        assert len(commands) > 20, (
            "the command catalogue parsed to almost nothing, so this gate would assert about an "
            "empty set — the incomplete-input failure this repository keeps meeting"
        )

        missing: list[str] = []
        for row in commands:
            action = row.get("audit_action")
            wanted = row.get("outbox_event")
            if not action or not wanted or action not in declared:
                # A command this milestone has not built yet, or one the catalogue gives no event.
                continue
            if declared[action] is None:
                missing.append(
                    f"{row.get('id')}: command_catalog names outbox_event {wanted!r} and "
                    f"{action!r} declares none"
                )

        assert missing == [], (
            "a catalogued command asks for an outbox event that no CommandNames declares. Nothing "
            "downstream fires and no test observes the absence:\n"
            + "\n".join(f"  {entry}" for entry in missing)
        )

    def test_an_uncatalogued_name_must_give_a_reason(self) -> None:
        """A typo must not become a permanent audit action string in silence."""

        with pytest.raises(ValueError, match="gives no reason"):
            CommandNames(
                audit_action="typo.acton", outbox_event_type=None, catalogued=False
            )

    def test_a_catalogued_name_must_not_also_claim_to_be_provisional(self) -> None:
        with pytest.raises(ValueError, match="needs no provisional reason"):
            CommandNames(
                audit_action="trader.approved",
                outbox_event_type=None,
                catalogued=True,
                provisional_reason="unnecessary",
            )

    def test_every_registered_name_states_its_catalogue_position(self) -> None:
        for names in ALL_COMMAND_NAMES:
            assert names.catalogued or names.provisional_reason

    def test_the_two_conventions_stay_distinct(self) -> None:
        """Dotted lowercase for audit, PascalCase for outbox — never normalised.

        A shared normaliser would look tidy and would rewrite one of them at the
        M0 freeze, which is the moment both have to stay exactly as approved.
        """

        assert RENAME_CENTER_PROFILE.audit_action.islower()
        assert "." in RENAME_CENTER_PROFILE.audit_action
        event = RENAME_CENTER_PROFILE.outbox_event_type
        assert event is not None
        assert event[0].isupper()
        assert "." not in event and "_" not in event

    def test_the_catalogue_is_read_from_the_governance_file(self) -> None:
        """Guard against the loader silently returning an empty set.

        Every membership assertion above would pass vacuously against one.
        """

        assert len(catalogued_audit_actions()) > 40
        assert len(catalogued_outbox_events()) > 5
        assert "trader.approved" in catalogued_audit_actions()


class TestTypedErrors:
    """Each status was previously reachable only via a bare HTTPException.

    That carries the number and loses everything else: a caller could not tell a
    stale version from a missing precondition, and no handler could attach a
    field-level detail.
    """

    @pytest.mark.parametrize(
        ("error", "code", "status"),
        [
            (IdempotencyKeyReusedError(), "IDEMPOTENCY_KEY_REUSED", 409),
            (VersionConflictError(), "VERSION_CONFLICT", 412),
            (PreconditionRequiredError("If-Match"), "PRECONDITION_REQUIRED", 428),
            (InvalidStateTransitionError(), "INVALID_STATE_TRANSITION", 400),
            (BusinessRuleViolationError("nope"), "BUSINESS_RULE_VIOLATION", 400),
            (NotFoundError(), "NOT_FOUND", 404),
        ],
    )
    def test_code_and_status_match_the_error_catalogue(
        self, error: AppError, code: str, status: int
    ) -> None:
        assert error.code == code
        assert error.status_code == status

    def test_a_missing_precondition_names_the_header(self) -> None:
        """428 has to be actionable; the caller needs to know which header."""

        error = PreconditionRequiredError("Idempotency-Key")

        assert error.details[0].field == "Idempotency-Key"
        assert "Idempotency-Key" in error.message

    def test_412_and_428_are_not_the_same_answer(self) -> None:
        """412 says reload and retry; 428 says the request was never safe.

        Collapsing them leaves a client retrying a request that can only fail
        again.
        """

        assert (
            VersionConflictError().status_code
            != PreconditionRequiredError("If-Match").status_code
        )

    def test_not_found_does_not_reveal_whether_the_resource_exists(self) -> None:
        assert "hidden" not in NotFoundError().message.lower()
        assert "permission" not in NotFoundError().message.lower()
