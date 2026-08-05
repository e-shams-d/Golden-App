"""Two identity tables, not one with a type flag.

`admin_users` and `trader_users` are separate because M3 has to prove that an
admin session is rejected on a trader surface and the reverse. With one table and
a `user_type` column that test is unfalsifiable: the same row satisfies both
queries, and the only thing standing between the two domains is a `WHERE` clause
somebody could forget. Two tables make the mistake a foreign-key error.

They are genuinely different, too. An admin logs in with a username; a trader
logs in with a phone number. A trader belongs to a business with exactly one
primary contact; an admin does not. Forcing both into one shape means half the
columns are null for half the rows and no constraint can say which half.

**The security stamp is the column doc 04 omits and doc 12 requires.** It appears
on both identity tables and again on the session record. Without the pair, a
password change or a role revocation cannot invalidate a live session: the
session is still signed, still unexpired, and still carries authority that was
taken away. Comparing the two versions at command time is what closes that, and
comparing needs both halves.

No authentication behaviour here — that is M3. This is the schema those commands
will need, built now so M3 does not have to invent it while also writing login.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    created_at_column,
    named_check,
    record_version_column,
    updated_at_column,
    uuid_primary_key,
)

# Argon2id encoded hashes run to about 100 characters at common parameters and
# grow with memory cost. Sized with room rather than measured against today's
# settings, because a truncated hash fails to verify and looks like a wrong
# password.
PASSWORD_HASH_LENGTH = 255


def security_stamp_column() -> Mapped[int]:
    """Bumped whenever authority changes: password, roles, forced logout.

    An integer rather than a UUID so a session carrying an older value is
    detectably older, not merely different — which matters when deciding whether
    to reject or refresh.
    """

    return mapped_column(BigInteger, nullable=False, server_default=text("1"))


class AdminUser(Base):
    """Staff identity. Logs in with a username."""

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    # CITEXT: usernames are compared case-insensitively, and doing it in the
    # column rather than in every query means no lookup can forget to lower().
    username: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Nullable with partial unique indexes below. A plain UNIQUE would allow many
    # NULLs in PostgreSQL — which is what is wanted — but stating it partially
    # makes the intent explicit rather than relying on a subtlety.
    email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)

    password_hash: Mapped[str] = mapped_column(String(PASSWORD_HASH_LENGTH), nullable=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # No value CHECK. `identity_account` is recorded in status_catalog.yaml with
    # `canonical: null`, so enumerating the states here would decide an open
    # question. Application-enforced fail-closed until M3 settles it.
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    security_stamp_version: Mapped[int] = security_stamp_column()

    # Durable in PostgreSQL, not Redis. `infra/redis/redis.conf` sets
    # `appendonly no` and `save ""` — zero persistence — so a Redis-only lockout
    # counter resets on restart and an attacker only has to wait for one.
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check("length(btrim(username::text)) > 0", name="username_not_blank"),
        named_check("failed_login_count >= 0", name="failed_login_count_not_negative"),
        named_check("security_stamp_version > 0", name="security_stamp_version_positive"),
        Index(
            "uq_admin_users_email",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        Index(
            "uq_admin_users_phone_number",
            "phone_number",
            unique=True,
            postgresql_where=text("phone_number IS NOT NULL"),
        ),
    )


class TraderUser(Base):
    """Trader identity. Logs in with a phone number."""

    __tablename__ = "trader_users"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    # The login identity, so uniqueness is unconditional rather than partial.
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)

    password_hash: Mapped[str] = mapped_column(String(PASSWORD_HASH_LENGTH), nullable=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # Which contact speaks for the trader business. The partial unique index
    # below has two conditions, and both are load-bearing: one primary contact,
    # but an inactive former primary must not block appointing a new one.
    is_primary: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )

    security_stamp_version: Mapped[int] = security_stamp_column()

    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check("length(btrim(phone_number)) > 0", name="phone_number_not_blank"),
        named_check("failed_login_count >= 0", name="failed_login_count_not_negative"),
        named_check("security_stamp_version > 0", name="security_stamp_version_positive"),
        Index(
            "uq_trader_users_primary_contact",
            "is_primary",
            unique=True,
            postgresql_where=text("is_primary = TRUE AND status <> 'inactive'"),
        ),
    )
