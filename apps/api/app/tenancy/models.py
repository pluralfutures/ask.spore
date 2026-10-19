"""Tenants, users and entitlements. Mirrors alembic revisions 0001, 0004 and 0006; the
migrations are authoritative."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

GEN_UUID = text("gen_random_uuid()")

# Seeded by alembic revision 0001: the Phase 0 tenant, now our own platform tenant.
INTERNAL_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

TENANT_STATUSES = ("active", "suspended")
USER_ROLES = ("user", "tenant_admin")
USER_STATUSES = ("invited", "active", "deactivated")
LOGIN_METHODS = ("sign_in_link",)
ANSWER_MODES = ("corpus_only", "general_knowledge")


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="status_valid"),
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'", name="slug_format"),
        CheckConstraint(
            "verified_domains = lower(verified_domains::text)::text[]", name="domains_lowercase"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=GEN_UUID
    )
    slug: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    verified_domains: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "email"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("role IN ('user', 'tenant_admin')", name="role_valid"),
        CheckConstraint("status IN ('invited', 'active', 'deactivated')", name="status_valid"),
        CheckConstraint("last_login_method IN ('sign_in_link')", name="login_method_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=GEN_UUID
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, server_default=text("'user'"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_method: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantEntitlements(Base):
    """What the operator has enabled for a tenant. One row per tenant."""

    __tablename__ = "tenant_entitlements"
    __table_args__ = (
        CheckConstraint(
            "answer_modes <@ ARRAY['corpus_only', 'general_knowledge']::text[] "
            "AND 'corpus_only' = ANY(answer_modes)",
            name="answer_modes_valid",
        ),
        CheckConstraint("external_spend_cap_cents >= 0", name="spend_cap_non_negative"),
        # P1a-03: external models only with the client's acceptance on file and a cap.
        CheckConstraint(
            "NOT external_models_enabled OR (length(btrim(external_acceptance_reference)) > 0 "
            "AND external_acceptance_date IS NOT NULL AND external_spend_cap_cents IS NOT NULL)",
            name="external_needs_acceptance",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    answer_modes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{corpus_only}'::text[]")
    )
    enabled_models: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    external_models_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    external_spend_cap_cents: Mapped[int | None] = mapped_column(Integer)
    sign_in_links_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # The client DPA document accepting external models, and its date (P1a-03).
    external_acceptance_reference: Mapped[str | None] = mapped_column(Text)
    external_acceptance_date: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
