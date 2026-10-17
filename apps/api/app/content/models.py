"""Source register and tag-to-dataset mapping. Shared corpus metadata, not tenant-scoped.

Mirrors alembic revision 0001; the migration is authoritative.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SOURCE_TYPES = ("pdf", "docx", "pptx", "html", "markdown")
SOURCE_STATUSES = ("registered", "ingesting", "ingested", "failed", "withdrawn")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(f"type IN {SOURCE_TYPES}", name="type_valid"),
        CheckConstraint(f"status IN {SOURCE_STATUSES}", name="status_valid"),
        CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="file_sha256_hex"),
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
    status: Mapped[str] = mapped_column(Text, server_default=text("'registered'"))
    file_sha256: Mapped[str | None] = mapped_column(Text)
    ragflow_document_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Dataset(Base):
    __tablename__ = "datasets"

    tag: Mapped[str] = mapped_column(Text, primary_key=True)
    ragflow_dataset_id: Mapped[str] = mapped_column(Text, unique=True)
