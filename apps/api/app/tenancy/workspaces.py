"""Workspaces and their tenant-authored prompts (P1a-04). Mirrors alembic revision 0007;
the migration is authoritative.

A workspace is the unit a user chooses when starting a conversation (architecture
§14.1): a set of content tags, resolved to dataset IDs server-side
(``app.chat.package.workspace_package``), an additional-instructions block written by
the tenant admin (``workspace_prompts``, latest version active), and defaults for
mode, model and reasoning. Every lookup here runs in a tenant-scoped transaction, so
RLS hides other tenants' workspaces; nothing here reads a request.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

PROMPT_MAX_CHARS = 2000  # P1a-06: the additional-instructions block, before escaping
_MODES = "('corpus_only', 'general_knowledge')"


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "slug"),
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'", name="slug_format"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 128", name="name_length"),
        CheckConstraint(f"default_mode IN {_MODES}", name="mode_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    slug: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    # Tag keys of config/tags.toml (the datasets primary key), never dataset IDs.
    tag_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    default_mode: Mapped[str] = mapped_column(Text, server_default=text("'corpus_only'"))
    default_model: Mapped[str] = mapped_column(Text)
    default_reasoning: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspacePrompt(Base):
    """One saved version of a workspace's additional instructions. Append-only."""

    __tablename__ = "workspace_prompts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "workspace_id", "version"),
        ForeignKeyConstraint(
            ["tenant_id", "workspace_id"],
            ["workspaces.tenant_id", "workspaces.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["tenant_id", "author_user_id"], ["users.tenant_id", "users.id"]),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(f"length(text) <= {PROMPT_MAX_CHARS}", name="text_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    author_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@dataclass(frozen=True)
class WorkspaceInstructions:
    """The active additional-instructions block: version 0 and empty text when none."""

    version: int
    text: str


NO_INSTRUCTIONS = WorkspaceInstructions(version=0, text="")


async def active_instructions(
    session: AsyncSession, workspace_id: uuid.UUID
) -> WorkspaceInstructions:
    """The latest saved version of the workspace's additional instructions."""
    row = (
        await session.execute(
            select(WorkspacePrompt.version, WorkspacePrompt.text)
            .where(WorkspacePrompt.workspace_id == workspace_id)
            .order_by(WorkspacePrompt.version.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return NO_INSTRUCTIONS
    return WorkspaceInstructions(version=row.version, text=row.text)


async def tenant_tags(session: AsyncSession) -> tuple[str, ...]:
    """The tenant's package: the union of its workspaces' tags (architecture §14.1)."""
    tags = await session.scalars(select(func.unnest(Workspace.tag_ids)).distinct())
    return tuple(sorted(tags))


class ChoiceRefused(ValueError):
    """The conversation cannot start with these settings. ``code`` is safe to return."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ConversationChoice:
    """Workspace, mode, model and reasoning of a new conversation, fixed from then on."""

    workspace_id: uuid.UUID
    mode: str
    model: str
    reasoning: bool


async def choose(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID | None,
    mode: str | None,
    model: str | None,
    reasoning: bool | None,
    answer_modes: Collection[str],
    models: Collection[str],
) -> ConversationChoice:
    """Validate the start-panel choice in the session's tenant, defaults from the workspace.

    ``answer_modes`` and ``models`` are what the tenant may use: its entitlements, the
    models further narrowed to what the platform can serve. A workspace of another
    tenant is invisible (RLS) and refused as ``unknown_workspace``. Without a
    workspace ID the tenant's only workspace is used (architecture §14.1).
    """
    if workspace_id is None:
        found = (await session.scalars(select(Workspace).limit(2))).all()
        if not found:
            raise ChoiceRefused("no_workspace")
        if len(found) > 1:
            raise ChoiceRefused("workspace_required")
        workspace = found[0]
    else:
        maybe = await session.scalar(select(Workspace).where(Workspace.id == workspace_id))
        if maybe is None:
            raise ChoiceRefused("unknown_workspace")
        workspace = maybe
    if mode is None:
        # A default the operator has since disabled falls back to corpus-only.
        mode = workspace.default_mode if workspace.default_mode in answer_modes else "corpus_only"
    if mode not in answer_modes:
        raise ChoiceRefused("mode_not_enabled")
    if model is None:
        fallback = sorted(models)
        model = workspace.default_model if workspace.default_model in models else None
        model = model or (fallback[0] if fallback else None)
    if model is None or model not in models:
        raise ChoiceRefused("model_not_enabled")
    return ConversationChoice(
        workspace_id=workspace.id,
        mode=mode,
        model=model,
        reasoning=workspace.default_reasoning if reasoning is None else reasoning,
    )
