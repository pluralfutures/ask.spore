"""Conversations, messages, citations and feedback. Tenant-scoped with RLS.

Child rows reference parents through composite (tenant_id, id) foreign keys, so a
row can never point at another tenant's row. Mirrors alembic revisions 0001, 0002 and
0007; the migrations are authoritative.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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

GEN_UUID = text("gen_random_uuid()")
RETENTION = "interval '30 days'"  # CLAUDE.md: chat history retention is 30 days maximum
MODES = "('corpus_only', 'general_knowledge')"  # answer modes of Phase 1a (P1a-06)


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=GEN_UUID)


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "workspace_id"], ["workspaces.tenant_id", "workspaces.id"]
        ),
        CheckConstraint(f"expires_at <= created_at + {RETENTION}", name="retention_cap"),
        CheckConstraint(f"mode IN {MODES}", name="mode_valid"),
        Index(None, "tenant_id", "user_id", "updated_at"),
        Index(None, "tenant_id", "expires_at"),
        Index(None, "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text(f"now() + {RETENTION}")
    )
    # P1a-04: chosen when the conversation is created and fixed for its lifetime (the
    # application role cannot UPDATE these columns).
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[bool] = mapped_column(Boolean)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("role IN ('user', 'assistant')", name="role_valid"),
        CheckConstraint(f"mode IN {MODES}", name="mode_valid"),
        CheckConstraint(
            "(role = 'user' AND outcome IS NULL) OR "
            "(role = 'assistant' AND outcome IN ('answered', 'unsupported', 'abstained'))",
            name="outcome_valid",
        ),
        Index(None, "tenant_id", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(Text, server_default=text("'corpus_only'"))
    model: Mapped[str | None] = mapped_column(Text)
    # Assistant messages (P1a-04): the conversation's reasoning setting.
    reasoning: Mapped[bool | None] = mapped_column(Boolean)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # Assistant messages only (revision 0002): answered | unsupported | abstained.
    outcome: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "message_id", "marker"),
        ForeignKeyConstraint(
            ["tenant_id", "message_id"], ["messages.tenant_id", "messages.id"], ondelete="CASCADE"
        ),
        CheckConstraint("marker > 0", name="marker_positive"),
    )

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    marker: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id"))
    ragflow_chunk_id: Mapped[str] = mapped_column(Text)
    page_or_slide: Mapped[int | None] = mapped_column(Integer)
    excerpt: Mapped[str] = mapped_column(Text)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "message_id", "user_id"),
        ForeignKeyConstraint(
            ["tenant_id", "message_id"], ["messages.tenant_id", "messages.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        CheckConstraint("rating IN ('up', 'down')", name="rating_valid"),
    )

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    rating: Mapped[str] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
