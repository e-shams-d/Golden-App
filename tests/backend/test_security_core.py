"""Password hashing, the actor context, and the session-secret mechanics.

No database and no HTTP: everything here is a property of the security primitives
themselves, and the point of the slice is that those properties hold before any
transport exists to confuse them.

Covers: SEC-PWD-001, SEC-PWD-002, SEC-PWD-003, SEC-PWD-004, SEC-SESS-001,
SEC-SESS-002, SEC-STAMP-001, SEC-EVENT-001, SVC-ACTOR-001.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.security.actor import ActorContext, ActorType, Audience
from app.security.events import (
    ALLOWED_METADATA_KEYS,
    OUTCOME_FAILURE,
    DisallowedEventMetadata,
    SecurityEvent,
    probe_correlation,
)
from app.security.passwords import (
    Argon2Parameters,
    PasswordTooLong,
    hash_password,
    verify_password,
)
from app.security.sessions import (
    SessionRejection,
    classify_identity,
    classify_stamp,
    digest_secret,
    generate_secret,
    is_well_formed,
)

SECURITY_PACKAGE = Path(__file__).resolve().parents[2] / "services" / "backend" / "app" / "security"

# Deliberately the cheapest parameters the settings floor permits. These tests
# assert behaviour, not cost, and every hash at the production defaults costs
# ~100ms — at a dozen calls that is a second of suite time buying nothing.
# `SEC-PWD-004` is the one test that needs two different parameter sets.
FAST = Argon2Parameters(time_cost=2, memory_cost_kib=65_536, parallelism=4)
MAX_LENGTH = 128


def test_a_correct_password_verifies_and_a_wrong_one_does_not() -> None:
    """SEC-PWD-001. Also: the stored value is not the password."""

    encoded = hash_password("hesabdar-1404", FAST, max_length=MAX_LENGTH)

    assert verify_password(encoded, "hesabdar-1404", FAST, max_length=MAX_LENGTH).is_valid
    assert not verify_password(encoded, "hesabdar-1405", FAST, max_length=MAX_LENGTH).is_valid
    assert "hesabdar-1404" not in encoded
    assert encoded.startswith("$argon2id$")


def test_the_same_password_hashes_differently_every_time() -> None:
    """SEC-PWD-002. Salting, observed rather than assumed.

    Without it, equal hashes reveal equal passwords across accounts, and a
    precomputed table works against the whole table at once.
    """

    first = hash_password("same-password", FAST, max_length=MAX_LENGTH)
    second = hash_password("same-password", FAST, max_length=MAX_LENGTH)

    assert first != second
    assert verify_password(first, "same-password", FAST, max_length=MAX_LENGTH).is_valid
    assert verify_password(second, "same-password", FAST, max_length=MAX_LENGTH).is_valid


def test_an_overlong_password_is_rejected_before_it_is_hashed() -> None:
    """SEC-PWD-003. The limit exists to avoid a cost, so it must precede the cost.

    Asserted by timing rather than by trusting the call order: a rejection that
    happened after hashing would take as long as a hash. The margin is wide
    because a wall-clock assertion that is tight is a flaky test.
    """

    too_long = "a" * (MAX_LENGTH + 1)

    started = datetime.now(UTC)
    with pytest.raises(PasswordTooLong):
        hash_password(too_long, FAST, max_length=MAX_LENGTH)
    elapsed = datetime.now(UTC) - started

    assert elapsed < timedelta(milliseconds=30), (
        f"rejection took {elapsed.total_seconds() * 1000:.0f}ms, which is long enough to "
        "have hashed first — the maximum length exists to avoid exactly that work"
    )

    # And on the verify path too, which is the one an attacker reaches without
    # credentials.
    encoded = hash_password("short", FAST, max_length=MAX_LENGTH)
    with pytest.raises(PasswordTooLong):
        verify_password(encoded, too_long, FAST, max_length=MAX_LENGTH)


def test_raising_the_parameters_marks_existing_hashes_for_rehash() -> None:
    """SEC-PWD-004. And the old hash still verifies, which is the whole point.

    If raising the cost invalidated stored hashes, nobody would ever raise it.
    """

    stronger = Argon2Parameters(time_cost=FAST.time_cost + 1, memory_cost_kib=65_536, parallelism=4)
    encoded = hash_password("unchanged", FAST, max_length=MAX_LENGTH)

    same = verify_password(encoded, "unchanged", FAST, max_length=MAX_LENGTH)
    upgraded = verify_password(encoded, "unchanged", stronger, max_length=MAX_LENGTH)

    assert same.is_valid and not same.needs_rehash
    assert upgraded.is_valid, "raising the cost must not invalidate an existing hash"
    assert upgraded.needs_rehash


def test_a_corrupt_hash_fails_the_login_rather_than_the_process() -> None:
    """A damaged row is a failed login, not a 500 that reveals the row is damaged."""

    result = verify_password("not-an-argon2-encoding", "anything", FAST, max_length=MAX_LENGTH)

    assert not result.is_valid
    assert not result.needs_rehash


def test_a_session_secret_is_high_entropy_and_unique() -> None:
    """SEC-SESS-001, first half."""

    secrets_seen = {generate_secret(32) for _ in range(64)}

    assert len(secrets_seen) == 64, "generate_secret repeated a value in 64 draws"
    for secret in secrets_seen:
        assert is_well_formed(secret)
        assert len(secret) >= 43


def test_the_stored_digest_is_not_the_secret_and_is_deterministic() -> None:
    """SEC-SESS-001, second half. A dump of digests must not yield sessions."""

    secret = generate_secret(32)
    digest = digest_secret(secret)

    assert secret not in digest
    assert digest == digest_secret(secret), "lookup by digest requires determinism"
    assert digest != digest_secret(generate_secret(32))
    assert digest.startswith("s1:")
    assert len(digest) <= 128, "the column holds 128 characters"


def test_a_secret_below_the_entropy_floor_is_refused() -> None:
    """The floor is the argument for using a fast hash; below it that argument fails."""

    with pytest.raises(ValueError, match="32 bytes"):
        generate_secret(16)


def test_malformed_secrets_never_reach_the_digest() -> None:
    """SEC-SESS-002's cheap half, and the reason `.encode("ascii")` is safe.

    A non-ASCII cookie would otherwise raise inside `digest_secret`, and the
    resulting `UnicodeEncodeError` quotes the offending text — which is part of a
    presented credential — into a stack trace.
    """

    for bad in ("", "short", "a" * 200, "valid-looking-but-has-a-space here", "کوکی-فارسی"):
        assert not is_well_formed(bad), f"{bad!r} passed the shape check"


def test_the_shape_check_accepts_the_whole_configurable_range() -> None:
    """Raising SESSION_SECRET_BYTES must not log out every live session.

    The pre-filter is keyed on the range the setting permits, not on its current
    value. Keyed on the current value, the deploy that raises it would reject
    every session issued before it — a fleet-wide logout reported as "sessions
    broke after the release".
    """

    for secret_bytes in (32, 48, 64):
        assert is_well_formed(generate_secret(secret_bytes))


def test_a_stamp_behind_the_identity_is_rejected_and_ahead_is_distinguished() -> None:
    """SEC-STAMP-001. The mechanism behind every revocation trigger doc 12 lists."""

    assert classify_stamp(4, 4) is None
    assert classify_stamp(3, 4) is SessionRejection.STAMP_BEHIND

    # Unreachable through this code, so reaching it means a restore or manual
    # editing. Equality rather than `>=` is what makes it visible instead of
    # silently acceptable.
    assert classify_stamp(5, 4) is SessionRejection.STAMP_AHEAD


def test_identity_state_is_evaluated_against_the_clock_not_a_status_value() -> None:
    """A lock is `locked_until`, per DOC-CONFLICT-037's decision."""

    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

    assert classify_identity("active", None, now) is None
    assert classify_identity("active", now - timedelta(seconds=1), now) is None
    assert classify_identity("active", now + timedelta(minutes=5), now) is (
        SessionRejection.IDENTITY_LOCKED
    )
    for status in ("suspended", "recovery_required", "deactivated"):
        assert classify_identity(status, None, now) is SessionRejection.IDENTITY_NOT_ACTIVE


def test_an_actor_context_cannot_mix_the_two_domains() -> None:
    """The context refuses to describe an actor the session row could not hold."""

    trader = ActorContext(
        actor_type=ActorType.TRADER_USER,
        actor_id=uuid.uuid4(),
        audience=Audience.TRADER,
        session_id=uuid.uuid4(),
        security_stamp_version=1,
        trader_id=uuid.uuid4(),
    )
    assert trader.is_trader
    assert trader.owns(trader.trader_id)
    assert not trader.owns(uuid.uuid4())

    with pytest.raises(ValueError, match="trader audience"):
        ActorContext(
            actor_type=ActorType.ADMIN_USER,
            actor_id=uuid.uuid4(),
            audience=Audience.TRADER,
            session_id=uuid.uuid4(),
            security_stamp_version=1,
            trader_id=uuid.uuid4(),
        )

    with pytest.raises(ValueError, match="no trader_id"):
        ActorContext(
            actor_type=ActorType.TRADER_USER,
            actor_id=uuid.uuid4(),
            audience=Audience.TRADER,
            session_id=uuid.uuid4(),
            security_stamp_version=1,
        )


def test_an_admin_actor_never_carries_trader_ownership() -> None:
    """Doc 12:316: an internal session is not ownership of a trader account."""

    admin = ActorContext(
        actor_type=ActorType.ADMIN_USER,
        actor_id=uuid.uuid4(),
        audience=Audience.ADMIN,
        session_id=uuid.uuid4(),
        security_stamp_version=1,
        permissions=frozenset({"user.read"}),
    )
    assert not admin.owns(uuid.uuid4())

    with pytest.raises(ValueError, match="carries a trader_id"):
        ActorContext(
            actor_type=ActorType.ADMIN_USER,
            actor_id=uuid.uuid4(),
            audience=Audience.ADMIN,
            session_id=uuid.uuid4(),
            security_stamp_version=1,
            trader_id=uuid.uuid4(),
        )


def test_a_trader_actor_cannot_carry_role_grants() -> None:
    """Doc 04:405 routes trader access through ownership, not `admin_user_roles`."""

    with pytest.raises(ValueError, match="role grants"):
        ActorContext(
            actor_type=ActorType.TRADER_USER,
            actor_id=uuid.uuid4(),
            audience=Audience.TRADER,
            session_id=uuid.uuid4(),
            security_stamp_version=1,
            trader_id=uuid.uuid4(),
            permissions=frozenset({"payment_batch.approve"}),
        )


def test_a_security_event_refuses_metadata_outside_the_allowlist() -> None:
    """SEC-EVENT-001. Construction fails; the row is never built.

    An allowlist because `auth_events` is append-only with no DELETE grant: a
    denylist's first miss is permanent.
    """

    ok = SecurityEvent(
        actor_type="trader_user",
        event_type="session.rejected",
        event_class="session",
        outcome=OUTCOME_FAILURE,
        metadata_payload={"rejection_reason": "revoked", "audience": "trader"},
    )
    assert ok.as_row()["metadata_schema"] == "auth_event.session.v1"
    assert ok.as_row()["metadata_version"] == 1

    for leaked in ("password", "secret", "secret_hash", "token", "cookie"):
        with pytest.raises(DisallowedEventMetadata, match=leaked):
            SecurityEvent(
                actor_type="trader_user",
                event_type="session.rejected",
                event_class="session",
                outcome=OUTCOME_FAILURE,
                metadata_payload={leaked: "s3cr3t-value"},
            )


def test_no_allowlisted_metadata_key_is_credential_shaped() -> None:
    """Guard the guard: the allowlist is only as good as what gets added to it."""

    forbidden = ("password", "secret", "token", "credential", "cookie", "hash", "digest")
    offenders = sorted(
        key for key in ALLOWED_METADATA_KEYS if any(word in key for word in forbidden)
    )

    assert offenders == [], (
        f"these allowlisted keys look credential-bearing: {offenders}. auth_events is "
        "append-only and the runtime cannot delete from it."
    )


def test_the_probe_correlation_is_not_the_stored_lookup_key() -> None:
    """Hashing the digest again is what stops a log export joining to the database.

    `secret_hash` is the indexed column. Recording it against a rejected probe
    would let anyone holding a log dump and a database dump match the probe to a
    live session row.
    """

    digest = digest_secret(generate_secret(32))
    correlation = probe_correlation(digest)

    assert correlation not in digest
    assert digest not in correlation
    assert correlation == probe_correlation(digest), "repeat probes must correlate"
    assert len(correlation) == 16


def test_the_security_package_imports_no_transport() -> None:
    """SVC-ACTOR-001. Transport-neutrality made structural rather than aspirational.

    `12_Security_RBAC_Audit.md:377` requires domain services to consume an
    `ActorContext` rather than transport claims, and ADR-001's approval records
    that the cookie decision stays reversible behind this interface. An interface
    that imports a `Request` is not reversible — it is the transport wearing a
    different name.

    Read from the AST rather than from `sys.modules`: an import inside a function
    would never execute during a test run and would go unnoticed.
    """

    forbidden = {"fastapi", "starlette", "app.api", "httpx", "flask"}
    offenders: list[str] = []

    for path in sorted(SECURITY_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if any(name == bad or name.startswith(f"{bad}.") for bad in forbidden):
                    offenders.append(f"{path.name}:{node.lineno} imports {name}")

    assert offenders == [], "app/security must stay transport-neutral:\n" + "\n".join(
        f"  {o}" for o in offenders
    )
