"""Operators and operator notices. Mirrors alembic revision 0006; the migration is
authoritative."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.tenancy.models import INTERNAL_TENANT_ID


class Operator(Base):
    """A user of the internal (platform) tenant who may use the operator console."""

    __tablename__ = "operators"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        CheckConstraint(f"tenant_id = '{INTERNAL_TENANT_ID}'::uuid", name="internal_tenant"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        server_default=text(f"'{INTERNAL_TENANT_ID}'::uuid"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OperatorNotice(Base):
    """Something the operator should look at (P1a-07 tenant-name matches, P1a-10 spend)."""

    __tablename__ = "operator_notices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        Index(None, "tenant_id", "created_at"),
        CheckConstraint("kind ~ '^[a-z][a-z0-9_]*(\\.[a-z0-9_]+)*$'", name="kind_format"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
