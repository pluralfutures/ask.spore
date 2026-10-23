"""Source register and tag-to-dataset mapping. Shared corpus metadata, not tenant-scoped.

Mirrors alembic revisions 0001, 0003, 0012, 0013, 0015, 0023, 0024 and 0060; the migrations
are authoritative.
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
# P1b-04: crawl management.
# P1c-14: withdrawn retires an approved site (revision 0060).
SITE_STATUSES = ("proposed", "approved", "rejected", "withdrawn")
SITE_SCHEDULES = ("none", "weekly", "monthly")
ALLOW_DECISIONS = ("unchecked", "allowed", "robots_disallowed", "tdm_reserved")
PAGE_STATES = ("live", "blocked", "removed")
MAX_SITE_PAGES = 5000
_CODE = "'^[a-z][a-z0-9_]{0,39}$'"


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
        CheckConstraint(
            "NOT takedown_licence_grounds OR takedown_requested_on IS NOT NULL",
            name="licence_grounds_need_takedown",
        ),
        CheckConstraint(
            "snapshot_path IS NULL OR snapshot_path ~ '^snapshots/[0-9a-f]{64}\\.html$'",
            name="snapshot_by_hash",
        ),
        Index(None, "takedown_due_on"),
        Index(None, "site_id"),
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
    # Revision 0023 (owner decision 5, Oct 22, 2026): the takedown is on licence grounds.
    # Since owner decision 3 (Oct 23, 2026) every withdrawal blanks the stored excerpts,
    # so the flag is a record for the queue and the audit trail only.
    takedown_licence_grounds: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Revision 0024 (P1b-04): a crawled page's site, its raw HTML snapshot under
    # ``[files] content_root`` (``snapshots/<sha256>.html``) and when it was fetched.
    site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id"))
    snapshot_path: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class Site(Base):
    """A registered website and its crawl settings (P1b-04, revision 0024)."""

    __tablename__ = "sites"
    __table_args__ = (
        CheckConstraint("start_url ~ '^https?://'", name="start_url_http"),
        CheckConstraint("cardinality(tags) >= 1", name="has_tags"),
        CheckConstraint(f"schedule IN {SITE_SCHEDULES}", name="schedule_valid"),
        CheckConstraint(f"max_pages BETWEEN 1 AND {MAX_SITE_PAGES}", name="max_pages_range"),
        CheckConstraint(f"status IN {SITE_STATUSES}", name="status_valid"),
        CheckConstraint(
            "status <> 'approved' OR approved_at IS NOT NULL", name="approval_recorded"
        ),
        CheckConstraint(
            "status <> 'withdrawn' OR (withdrawn_at IS NOT NULL "
            "AND length(btrim(coalesce(withdrawal_reason, ''))) > 0)",
            name="withdrawal_recorded",
        ),
        CheckConstraint(f"allow_decision IN {ALLOW_DECISIONS}", name="allow_decision_valid"),
        CheckConstraint(
            f"last_crawl_status IS NULL OR last_crawl_status ~ {_CODE}",
            name="last_crawl_status_code",
        ),
        CheckConstraint("page_count >= 0", name="page_count_non_negative"),
        Index(None, "status", "next_crawl_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    start_url: Mapped[str] = mapped_column(Text, unique=True)
    host: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    licence_basis: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    allow_patterns: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    deny_patterns: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    special_category_allow: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    schedule: Mapped[str] = mapped_column(Text, server_default=text("'none'"))
    max_pages: Mapped[int] = mapped_column(Integer, server_default=text("50"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'proposed'"))
    allow_decision: Mapped[str] = mapped_column(Text, server_default=text("'unchecked'"))
    allow_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_crawl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_crawl_status: Mapped[str | None] = mapped_column(Text)
    next_crawl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Revision 0060 (P1c-14): a reviewer withdrew the whole site.
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawal_reason: Mapped[str | None] = mapped_column(Text)


class SitePage(Base):
    """One page URL a crawl met: live (its current register row), blocked or removed."""

    __tablename__ = "site_pages"
    __table_args__ = (
        CheckConstraint(f"state IN {PAGE_STATES}", name="state_valid"),
        CheckConstraint(
            f"(state = 'live') = (reason IS NULL) AND (reason IS NULL OR reason ~ {_CODE})",
            name="reason_when_not_live",
        ),
        CheckConstraint("state <> 'live' OR source_id IS NOT NULL", name="live_has_source"),
        CheckConstraint(
            f"special_category IS NULL OR special_category ~ {_CODE}",
            name="special_category_code",
        ),
        Index(None, "source_id"),
    )

    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True
    )
    url: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    special_category: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id")
    )
    published_on: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
