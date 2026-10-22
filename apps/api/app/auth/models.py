"""Pending sign-in links and SSO attempts, and revoked sessions. Mirrors alembic revisions
0005, 0010, 0021 and 0022; the migrations are authoritative."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SignInLink(Base):
    """One link request for a known user, bound to the browser that asked for it."""

    __tablename__ = "sign_in_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        Index(None, "tenant_id", "user_id", "created_at"),
        CheckConstraint("expires_at <= created_at + interval '15 minutes'", name="expiry_cap"),
        CheckConstraint(
            "binding_hash ~ '^[0-9a-f]{64}$' AND token_hash ~ '^[0-9a-f]{64}$'", name="hashes_hex"
        ),
        CheckConstraint("(consumed_at IS NULL) = (token_hash IS NULL)", name="consumed_with_token"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    binding_hash: Mapped[str] = mapped_column(Text, unique=True)
    token_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RevokedSession(Base):
    """An access token whose holder signed out (P1a-02). Only its SHA-256 is kept."""

    __tablename__ = "revoked_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        CheckConstraint("token_sha256 ~ '^[0-9a-f]{64}$'", name="token_sha256_hex"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    token_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SsoAttempt(Base):
    """One SSO sign-in started from the login page (P1b-07), bound to that browser."""

    __tablename__ = "sso_attempts"
    __table_args__ = (
        Index(None, "tenant_id", "created_at"),
        CheckConstraint("expires_at <= created_at + interval '10 minutes'", name="expiry_cap"),
        CheckConstraint("binding_hash ~ '^[0-9a-f]{64}$'", name="binding_hash_hex"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    binding_hash: Mapped[str] = mapped_column(Text, unique=True)
    source_slug: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


MAX_MFA_ATTEMPTS = 5


class MfaChallenge(Base):
    """A tenant admin's pending second factor in a sign-in-link flow (P1b-08)."""

    __tablename__ = "mfa_challenges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        Index(None, "tenant_id", "user_id", "created_at"),
        CheckConstraint("expires_at <= created_at + interval '5 minutes'", name="expiry_cap"),
        CheckConstraint(f"attempts BETWEEN 0 AND {MAX_MFA_ATTEMPTS}", name="attempts_cap"),
        CheckConstraint("binding_hash ~ '^[0-9a-f]{64}$'", name="binding_hash_hex"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    binding_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
