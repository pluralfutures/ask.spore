"""Which model answers a conversation, and whether the tenant may use it (P1a-09).

The orchestrator calls ``authorize`` inside its tenant-scoped transaction, before any
outbound call (query rewrite, retrieval or generation): a refusal ends the turn with an
error event (audited) and nothing leaves the API.

Integration with P1a-04 (Group B): conversations gain ``model`` and ``reasoning``
columns, fixed at creation. Until that migration exists, ``conversation_choice``
falls back to the tenant default (``app.tenancy.entitlements.tenant_default_choice``,
the stand-in for the workspace default, findings C1); once the ORM model has the
columns it reads them, and a conversation without a model also falls back.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import Conversation
from app.core.config import CatalogueEntry, Settings
from app.llm.catalogue import ModelChoice
from app.tenancy.entitlements import (
    ModelEntitlement,
    ModelRefused,
    RefusalCode,
    check_choice,
    tenant_default_choice,
)
from app.tenancy.models import TenantEntitlements


async def load_entitlement(session: AsyncSession, tenant_id: uuid.UUID) -> ModelEntitlement:
    """The tenant's model entitlement, read under its RLS scope."""
    return ModelEntitlement.of(await session.get(TenantEntitlements, tenant_id))


async def conversation_choice(
    session: AsyncSession, conversation_id: uuid.UUID, fallback: ModelChoice | None
) -> ModelChoice | None:
    """The conversation's fixed model choice, or ``fallback`` while it has none."""
    model_col: Any = getattr(Conversation, "model", None)
    reasoning_col: Any = getattr(Conversation, "reasoning", None)
    if model_col is None or reasoning_col is None:
        return fallback  # before P1a-04's columns exist
    row = (
        await session.execute(
            select(model_col, reasoning_col).where(Conversation.id == conversation_id)
        )
    ).one_or_none()
    if row is None or row[0] is None:
        return fallback
    return ModelChoice(str(row[0]), bool(row[1]))


@dataclass(frozen=True)
class Authorization:
    """The conversation's model choice and its catalogue entry, or why it is refused."""

    choice: ModelChoice | None
    model: CatalogueEntry | None
    refusal: RefusalCode | None


async def authorize(
    session: AsyncSession, settings: Settings, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> Authorization:
    """The conversation's model choice, checked against the tenant's entitlement.

    Reads only; makes no outbound call.
    """
    ent = await load_entitlement(session, tenant_id)
    choice = await conversation_choice(
        session, conversation_id, tenant_default_choice(settings, ent)
    )
    try:
        if choice is None:
            raise ModelRefused("model_not_enabled")
        return Authorization(choice, check_choice(settings, ent, choice), None)
    except ModelRefused as exc:
        return Authorization(choice, None, exc.code)
