"""Which model answers a conversation, and whether the tenant may use it (P1a-09,
P1a-10).

The orchestrator calls ``authorize`` inside its tenant-scoped transaction, before any
outbound call (query rewrite, retrieval or generation): a refusal ends the turn with an
error event (audited) and nothing leaves the API. An external model whose tenant has
reached its monthly spend cap is refused there too (hard stop).

``choose_for_new_conversation`` is what creating a conversation calls: it checks the
requested choice and, when the external spend cap is reached, falls back to the default
model with a user-facing notice and an audit event.

Integration with P1a-04 (Group B): conversations gain ``model`` and ``reasoning``
columns, fixed at creation. Until that migration exists, ``conversation_choice``
falls back to the tenant default (``app.tenancy.entitlements.tenant_default_choice``,
the stand-in for the workspace default, findings C1); once the ORM model has the
columns it reads them, and a conversation without a model also falls back. P1a-04's
create route stores ``choose_for_new_conversation(...).choice`` in those columns and
returns the notice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import record
from app.chat.models import Conversation, Message
from app.core.config import CatalogueEntry, Settings
from app.llm import catalogue
from app.llm.catalogue import ModelChoice
from app.tenancy.entitlements import (
    ModelEntitlement,
    ModelRefused,
    RefusalCode,
    check_choice,
    tenant_default_choice,
)
from app.tenancy.models import TenantEntitlements
from app.usage.ledger import cap_reached

# User-facing notice when a new conversation falls back from an external model (P1a-10).
SPEND_CAP_NOTICE = "external_spend_cap_reached"
SPEND_CAP_TEXT = (
    "This month's budget for models served outside the EU has been used up. "
    "This conversation uses {model} instead."
)


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


def message_choice_fields(choice: ModelChoice | None) -> dict[str, Any]:
    """The reasoning flag for an assistant ``Message``, once P1a-04 adds the column.

    The model is already stored (``messages.model``); ``messages.reasoning`` arrives with
    Group B's migration, and until then there is nowhere to store it (findings C15).
    """
    if choice is None or not hasattr(Message, "reasoning"):
        return {}
    return {"reasoning": choice.reasoning}


@dataclass(frozen=True)
class Authorization:
    """The conversation's model choice and its catalogue entry, or why it is refused."""

    choice: ModelChoice | None
    model: CatalogueEntry | None
    refusal: RefusalCode | None
    entitlement: ModelEntitlement | None = None


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
        model = check_choice(settings, ent, choice)
        if model.external and await cap_reached(session, settings, tenant_id, ent):
            raise ModelRefused("spend_cap_reached")
        return Authorization(choice, model, None, ent)
    except ModelRefused as exc:
        return Authorization(choice, None, exc.code, ent)


@dataclass(frozen=True)
class Selection:
    """The model choice a new conversation is created with, and any notice to show."""

    choice: ModelChoice
    notice: str | None = None  # SPEND_CAP_NOTICE
    notice_text: str | None = None


async def choose_for_new_conversation(
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    requested: ModelChoice | None,
) -> Selection:
    """Check the user's choice (or take the default) for a new conversation.

    Raises ``ModelRefused`` for a model the tenant may not use. An external model whose
    tenant has reached the monthly spend cap falls back to the default model, keeping
    reasoning on only where that model has a switch; the fallback is audited
    (``model.fallback``) and the selection carries the user-facing notice.
    """
    ent = await load_entitlement(session, tenant_id)
    default = tenant_default_choice(settings, ent)
    choice = requested or default
    if choice is None:
        raise ModelRefused("model_not_enabled")
    model = check_choice(settings, ent, choice)
    if not (model.external and await cap_reached(session, settings, tenant_id, ent)):
        return Selection(choice)
    fallback_model = catalogue.entry(settings, default.model) if default else None
    if default is None or fallback_model is None:
        raise ModelRefused("spend_cap_reached")
    fallback = ModelChoice(default.model, choice.reasoning and fallback_model.reasoning != "none")
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=user_id,
        event="model.fallback",
        metadata={
            "model": fallback.model,
            "reasoning": fallback.reasoning,
            "requested_model": choice.model,
            "error_code": "spend_cap_reached",
        },
    )
    return Selection(
        fallback, SPEND_CAP_NOTICE, SPEND_CAP_TEXT.format(model=fallback_model.display_name)
    )
