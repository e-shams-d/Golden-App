"""Step-up assurance and separation of duties, as pure policy.

Both modules are deliberately I/O-free, so every rejection branch is reachable
without a database and the tests can produce states a healthy system never
reaches — a consumed context, a revoked one, a factor that used to be registered.

Covers: SEC-STEP-001, SEC-STEP-002, SEC-STEP-003, SEC-STEP-004, SEC-STEP-005,
SEC-STEP-006, SEC-SOD-001, SEC-SOD-002.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.security import step_up
from app.security.actor import ActorContext, ActorType, Audience
from app.security.separation_of_duties import (
    ApprovalAttempt,
    SeparationRefusal,
    is_permitted,
    refusal_for,
)
from app.security.step_up import (
    PresentedContext,
    StepUpRejection,
    StepUpRequest,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
PURPOSE = "payment_batch_approval"
RESOURCE_TYPE = "payment_batch_version"


def admin(actor_id: uuid.UUID | None = None, session_id: uuid.UUID | None = None) -> ActorContext:
    return ActorContext(
        actor_type=ActorType.ADMIN_USER,
        actor_id=actor_id or uuid.uuid4(),
        audience=Audience.ADMIN,
        session_id=session_id or uuid.uuid4(),
        security_stamp_version=1,
    )


def stored_for(
    actor: ActorContext,
    resource_id: uuid.UUID,
    **overrides: object,
) -> PresentedContext:
    fields: dict[str, object] = {
        "actor_id": actor.actor_id,
        "session_id": actor.session_id,
        "purpose": PURPOSE,
        "resource_type": RESOURCE_TYPE,
        "resource_id": resource_id,
        "assurance_factor": step_up.PASSWORD_FACTOR,
        "expires_at": NOW + timedelta(minutes=5),
        "consumed_at": None,
        "revoked_at": None,
    }
    fields.update(overrides)
    return PresentedContext(**fields)  # type: ignore[arg-type]


def request_for(resource_id: uuid.UUID, **overrides: object) -> StepUpRequest:
    fields: dict[str, object] = {
        "purpose": PURPOSE,
        "resource_type": RESOURCE_TYPE,
        "resource_id": resource_id,
    }
    fields.update(overrides)
    return StepUpRequest(**fields)  # type: ignore[arg-type]


class TestStepUpBindings:
    def test_a_matching_context_authorises_the_command(self) -> None:
        """SEC-STEP-001's positive half. Without it every test below is vacuous."""

        actor = admin()
        resource = uuid.uuid4()

        assert (
            step_up.rejection_for(
                stored_for(actor, resource),
                actor=actor,
                request=request_for(resource),
                now=NOW,
            )
            is None
        )

    def test_an_unknown_reference_is_refused(self) -> None:
        actor = admin()
        assert (
            step_up.rejection_for(None, actor=actor, request=request_for(uuid.uuid4()), now=NOW)
            is StepUpRejection.UNKNOWN_REFERENCE
        )

    def test_another_actors_context_is_refused(self) -> None:
        """Otherwise one person's step-up authorises another's command."""

        holder = admin()
        resource = uuid.uuid4()
        someone_else = admin(session_id=holder.session_id)

        assert (
            step_up.rejection_for(
                stored_for(holder, resource),
                actor=someone_else,
                request=request_for(resource),
                now=NOW,
            )
            is StepUpRejection.WRONG_ACTOR
        )

    def test_a_context_from_another_session_is_refused(self) -> None:
        """SEC-STEP-003. `12_Security_RBAC_Audit.md:556` prohibits it in terms.

        Same person, different session: a context obtained on a laptop must not
        authorise a command from a phone that has since been stolen.
        """

        actor_id = uuid.uuid4()
        laptop = admin(actor_id=actor_id)
        phone = admin(actor_id=actor_id)
        resource = uuid.uuid4()

        assert (
            step_up.rejection_for(
                stored_for(laptop, resource),
                actor=phone,
                request=request_for(resource),
                now=NOW,
            )
            is StepUpRejection.WRONG_SESSION
        )

    def test_a_context_for_another_purpose_is_refused(self) -> None:
        """SEC-STEP-002. A step-up to change a password must not approve a batch."""

        actor = admin()
        resource = uuid.uuid4()

        assert (
            step_up.rejection_for(
                stored_for(actor, resource, purpose="password_change"),
                actor=actor,
                request=request_for(resource),
                now=NOW,
            )
            is StepUpRejection.WRONG_PURPOSE
        )

    def test_a_context_for_another_resource_is_refused(self) -> None:
        """The case the whole approval model exists to prevent.

        Same actor, same session, same purpose, different batch version. Without
        the resource binding, a step-up for version 7 approves version 8 — and
        version 8 is whatever somebody replaced version 7 with.
        """

        actor = admin()

        assert (
            step_up.rejection_for(
                stored_for(actor, uuid.uuid4()),
                actor=actor,
                request=request_for(uuid.uuid4()),
                now=NOW,
            )
            is StepUpRejection.WRONG_RESOURCE
        )

        # And a matching id under a different resource *type* is still refused.
        shared_id = uuid.uuid4()
        assert (
            step_up.rejection_for(
                stored_for(actor, shared_id, resource_type="admin_user"),
                actor=actor,
                request=request_for(shared_id),
                now=NOW,
            )
            is StepUpRejection.WRONG_RESOURCE
        )


class TestStepUpLifecycle:
    def test_an_expired_context_is_refused(self) -> None:
        """SEC-STEP-004, evaluated against the clock the caller does not supply."""

        actor = admin()
        resource = uuid.uuid4()

        assert (
            step_up.rejection_for(
                stored_for(actor, resource, expires_at=NOW - timedelta(seconds=1)),
                actor=actor,
                request=request_for(resource),
                now=NOW,
            )
            is StepUpRejection.EXPIRED
        )

    def test_a_consumed_context_is_refused_a_second_time(self) -> None:
        """SEC-STEP-005. One step-up must not authorise two effects."""

        actor = admin()
        resource = uuid.uuid4()

        assert (
            step_up.rejection_for(
                stored_for(actor, resource, consumed_at=NOW - timedelta(seconds=1)),
                actor=actor,
                request=request_for(resource),
                now=NOW,
            )
            is StepUpRejection.ALREADY_CONSUMED
        )

    def test_a_revoked_context_is_refused(self) -> None:
        actor = admin()
        resource = uuid.uuid4()

        assert (
            step_up.rejection_for(
                stored_for(actor, resource, revoked_at=NOW - timedelta(seconds=1)),
                actor=actor,
                request=request_for(resource),
                now=NOW,
            )
            is StepUpRejection.REVOKED
        )

    def test_a_factor_no_longer_registered_is_refused(self) -> None:
        """Fail closed on assurance this deployment has stopped accepting.

        The row records which factor was used, so a context written when `sms` was
        registered stays identifiable after it is withdrawn — and is then refused
        rather than honoured on the strength of a decision that was reversed.
        """

        actor = admin()
        resource = uuid.uuid4()

        assert (
            step_up.rejection_for(
                stored_for(actor, resource, assurance_factor="sms"),
                actor=actor,
                request=request_for(resource),
                now=NOW,
            )
            is StepUpRejection.UNREGISTERED_FACTOR
        )

    def test_identity_is_checked_before_staleness(self) -> None:
        """A replay of someone else's expired reference reads as the wrong actor.

        The client cannot tell the difference — it gets one error either way — but
        an investigator reading `auth_events` can, and "somebody replayed another
        actor's reference" is a materially different event from "somebody was slow".
        """

        holder = admin()
        resource = uuid.uuid4()
        attacker = admin(session_id=holder.session_id)

        assert (
            step_up.rejection_for(
                stored_for(holder, resource, expires_at=NOW - timedelta(hours=1)),
                actor=attacker,
                request=request_for(resource),
                now=NOW,
            )
            is StepUpRejection.WRONG_ACTOR
        )


class TestStepUpMechanics:
    def test_the_reference_is_never_stored(self) -> None:
        reference = step_up.generate_reference()
        digest = step_up.digest_reference(reference)

        assert reference not in digest
        assert len(digest) == 64
        assert digest == step_up.digest_reference(reference), "lookup needs stability"

    def test_two_references_differ(self) -> None:
        assert step_up.generate_reference() != step_up.generate_reference()

    def test_only_the_registered_factor_is_accepted(self) -> None:
        """ADR-009 decides what else joins it; until then, one entry."""

        assert step_up.require_registered_factor("password") == "password"

        for unregistered in ("sms", "totp", "webauthn", ""):
            with pytest.raises(ValueError, match="ADR-009"):
                step_up.require_registered_factor(unregistered)

    def test_a_policy_that_expires_immediately_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot be presented"):
            step_up.StepUpPolicy(lifetime_seconds=0)


class TestSeparationOfDuties:
    def test_two_different_identities_may_prepare_and_approve(self) -> None:
        approver = admin()
        attempt = ApprovalAttempt(finalizer_actor_id=uuid.uuid4(), approver=approver)

        assert refusal_for(attempt) is None
        assert is_permitted(attempt)

    def test_the_same_identity_cannot_do_both(self) -> None:
        """SEC-SOD-001. DOC-CONFLICT-021, Approved: mandatory, not configurable."""

        approver = admin()
        attempt = ApprovalAttempt(finalizer_actor_id=approver.actor_id, approver=approver)

        assert refusal_for(attempt) is SeparationRefusal.SAME_IDENTITY
        assert not is_permitted(attempt)

    def test_no_configuration_changes_the_outcome(self) -> None:
        """The absence of a switch, asserted rather than assumed.

        A flag defaulting to "on" is a flag somebody turns off during an incident
        at 2am, which is exactly when the control matters. This reads the module's
        source for any settings access, because the strongest form of "cannot be
        configured off" is having nothing to read.
        """

        from pathlib import Path

        source = Path("services/backend/app/security/separation_of_duties.py")
        if not source.is_file():  # pragma: no cover - path differs under some runners
            import app.security.separation_of_duties as module

            source = Path(module.__file__)
        text = source.read_text(encoding="utf-8")

        for forbidden in ("load_settings", "Settings", "os.environ", "getenv", "FeatureFlag"):
            assert forbidden not in text, (
                f"separation_of_duties.py references {forbidden!r}. "
                "FINANCIAL_INTEGRITY_BASELINE.md section 5 makes finalizer != approver "
                "non-configurable; a reachable switch is the thing that is forbidden."
            )

    def test_a_worker_cannot_even_hold_an_actor_context(self) -> None:
        """SEC-SOD-002, and the guarantee turned out to be stronger than expected.

        `14_Testing_QA_Acceptance.md:1294` requires that a worker cannot execute a
        human financial command, and doc 12:357 says system actors exercise no
        approval authority. The plan for this test was to hand a worker to the
        separation check and watch it refuse.

        It cannot get that far. `Audience` has exactly two values and
        `ActorContext.__post_init__` requires the actor type to match one of them,
        so a `system_worker` cannot be represented as an authenticated actor at
        all — the refusal happens at construction, one layer earlier than the
        policy.

        `HUMAN_ACTOR_TYPES` in `separation_of_duties` therefore guards a case that
        cannot currently arrive. It is kept as an allowlist rather than deleted,
        because the day `Audience` gains a system value is the day it starts
        mattering, and an allowlist fails closed on a value nobody has considered.
        """

        for actor_type in (ActorType.SYSTEM_WORKER, ActorType.SYSTEM_MAINTENANCE):
            for audience in (Audience.ADMIN, Audience.TRADER):
                with pytest.raises(ValueError, match="actor_type"):
                    ActorContext(
                        actor_type=actor_type,
                        actor_id=uuid.uuid4(),
                        audience=audience,
                        session_id=uuid.uuid4(),
                        security_stamp_version=1,
                        trader_id=uuid.uuid4() if audience is Audience.TRADER else None,
                    )

    def test_the_separation_check_still_refuses_a_non_human_actor_type(self) -> None:
        """The second line, exercised directly.

        Constructed by replacing the field on a valid context rather than through
        the constructor, because the constructor is what refuses it. This proves
        `HUMAN_ACTOR_TYPES` is not dead code that would silently permit a worker
        if `ActorContext` ever admitted one.
        """

        # `object.__setattr__` rather than the constructor or `dataclasses.replace`,
        # because both run the validator that refuses this — which is the fact the
        # test above establishes. Reaching past it is the only way to exercise the
        # layer behind it, and a guard nobody can reach is a guard nobody can trust
        # to still work when it starts being reachable.
        worker = admin()
        object.__setattr__(worker, "actor_type", ActorType.SYSTEM_WORKER)

        attempt = ApprovalAttempt(finalizer_actor_id=uuid.uuid4(), approver=worker)

        assert refusal_for(attempt) is SeparationRefusal.NOT_A_HUMAN_ACTOR

    def test_an_approval_with_no_recorded_finalizer_is_refused(self) -> None:
        """Missing is not "different from everyone".

        A version with no recorded preparer cannot satisfy a rule about two
        different people, and treating `None` as distinct is how a separation
        check passes on incomplete data.
        """

        attempt = ApprovalAttempt(finalizer_actor_id=None, approver=admin())

        assert refusal_for(attempt) is SeparationRefusal.NO_FINALIZER_RECORDED
