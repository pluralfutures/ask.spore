"""Support grants (P2A-08). Mirrors alembic revision 0065; the migration is authoritative."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCOPES = ("settings", "conversation")
MIN_MINUTES = 15
MAX_MINUTES = 240
DEFAULT_MINUTES = 60
MAX_NOTE_CHARS = 500


class SupportGrant(Base):
    __tablename__ = "support_grants"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("scope IN ('settings', 'conversation')", name="scope_valid"),
        CheckConstraint(
            "(scope = 'conversation') = (conversation_id IS NOT NULL)", name="conversation_scope"
        ),
        CheckConstraint(
            f"duration_minutes BETWEEN {MIN_MINUTES} AND {MAX_MINUTES}", name="duration_range"
        ),
        Index(None, "tenant_id", "created_at"),
        Index(None, "tenant_id", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    scope: Mapped[str] = mapped_column(Text)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
