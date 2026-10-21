"""Source register and tag-to-dataset mapping. Shared corpus metadata, not tenant-scoped.

Mirrors alembic revisions 0001, 0003, 0012, 0013 and 0015; the migrations are
authoritative.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.tenancy.models import INTERNAL_TENANT_ID

SOURCE_TYPES = ("pdf", "docx", "pptx", "html", "markdown")
# P1b-01: proposed -> approved -> ingested -> withdrawn; failed is retryable (back to
# approved); rejected ends a proposal a reviewer declined.
SOURCE_STATUSES = ("proposed", "approved", "ingested", "failed", "withdrawn", "rejected")
CONTENT_ROLES = ("content_editor", "content_reviewer")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(f"type IN {SOURCE_TYPES}", name="type_valid"),
        CheckConstraint(f"status IN {SOURCE_STATUSES}", name="status_valid"),
        CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="file_sha256_hex"),
        CheckConstraint("error IS NULL OR status = 'failed'", name="error_only_when_failed"),
        CheckConstraint("chunk_count >= 0", name="chunk_count_non_negative"),
        CheckConstraint(
            "stored_path IS NULL OR (type IN ('pdf', 'docx', 'pptx') AND stored_path = "
            "substr(file_sha256, 1, 2) || '/' || file_sha256 || '.' || type)",
            name="stored_path_by_hash",
        ),
        CheckConstraint(
            "status IN ('proposed', 'rejected') OR approved_at IS NOT NULL",
            name="approval_recorded",
        ),
        CheckConstraint(
            "status <> 'withdrawn' OR (withdrawn_at IS NOT NULL "
            "AND length(btrim(coalesce(withdrawal_reason, ''))) > 0)",
            name="withdrawal_recorded",
        ),
        CheckConstraint(
            "licence_file_path IS NULL OR "
            "licence_file_path ~ '^licences/[0-9a-f]{64}\\.[a-z0-9]{1,8}$'",
            name="licence_file_by_hash",
        ),
        CheckConstraint("supersedes_id IS DISTINCT FROM id", name="supersedes_another"),
        CheckConstraint(
            "(takedown_requested_on IS NULL AND takedown_due_on IS NULL) OR "
            "(length(btrim(coalesce(takedown_reference, ''))) > 0 "
            "AND takedown_requested_on IS NOT NULL "
            "AND takedown_due_on >= takedown_requested_on)",
            name="takedown_recorded",
        ),
        Index(None, "takedown_due_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    type: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    published_on: Mapped[date | None] = mapped_column(Date)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    licence_basis: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'proposed'"))
    file_sha256: Mapped[str | None] = mapped_column(Text)
    # {ragflow_dataset_id: ragflow_document_id}, one entry per tag the source is in.
    ragflow_document_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    # Revision 0003 (P0-09): ingestion results.
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    # Revision 0012 (P1a-14): the licence gate for downloads, and our own stored copy
    # (``app.content.store``), relative to ``[files] content_root``.
    downloadable: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    stored_path: Mapped[str | None] = mapped_column(Text)
    # Revision 0013 (P1b-01): who proposed and approved it (internal users, no foreign
    # key, like audit actors), withdrawal, takedown and review metadata, and the licence
    # or permission letter under ``[files] content_root`` (never in RAGFlow).
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawal_reason: Mapped[str | None] = mapped_column(Text)
    takedown_reference: Mapped[str | None] = mapped_column(Text)
    review_date: Mapped[date | None] = mapped_column(Date)
    licence_file_path: Mapped[str | None] = mapped_column(Text)
    review_note: Mapped[str | None] = mapped_column(Text)
    # Revision 0015 (P1b-03): the source a re-ingested file replaces, and the takedown
    # queue's request date and due date (10 working days, or at once for a licence
    # breach we find ourselves).
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id")
    )
    takedown_requested_on: Mapped[date | None] = mapped_column(Date)
    takedown_due_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Dataset(Base):
    __tablename__ = "datasets"

    tag: Mapped[str] = mapped_column(Text, primary_key=True)
    ragflow_dataset_id: Mapped[str] = mapped_column(Text, unique=True)


class ContentRole(Base):
    """A content role held by a user of the internal tenant (P1b-01, revision 0013)."""

    __tablename__ = "content_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        CheckConstraint(f"tenant_id = '{INTERNAL_TENANT_ID}'::uuid", name="internal_tenant"),
        CheckConstraint(f"role IN {CONTENT_ROLES}", name="role_valid"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        server_default=text(f"'{INTERNAL_TENANT_ID}'::uuid"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(Text, primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
