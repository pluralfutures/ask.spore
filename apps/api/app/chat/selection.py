"""Which model answers a conversation, and whether the tenant may use it (P1a-09,
P1a-10).

The orchestrator calls ``authorize`` inside its tenant-scoped transaction, before any
outbound call (query rewrite, retrieval or generation): a refusal ends the turn with an
error event (audited) and nothing leaves the API. An external model whose tenant has
reached its monthly spend cap is refused there too (hard stop).

``choose_for_new_conversation`` is what creating a conversation calls (P1a-04's
route): it checks the requested choice, or the workspace's default model and
reasoning, and, when the external spend cap is reached, falls back to the workspace
default model with a user-facing notice and an audit event. The route stores the
returned ``choice`` in ``conversations.model`` and ``reasoning`` (Group B's columns,
fixed at creation); ``conversation_choice`` reads them back for every answer and
``message_choice_fields`` writes ``messages.reasoning``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import record
from app.chat.models import Conversation
from app.core.config import CatalogueEntry, Settings
from app.llm import catalogue
from app.llm.catalogue import ModelChoice
from app.tenancy.entitlements import (
    ModelEntitlement,
    ModelRefused,
    RefusalCode,
    check_choice,
    eu_fallback_choice,
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
    session: AsyncSession, conversation_id: uuid.UUID
) -> ModelChoice | None:
    """The conversation's model choice, fixed at creation; None without a visible row."""
    row = (
        await session.execute(
            select(Conversation.model, Conversation.reasoning).where(
                Conversation.id == conversation_id
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return ModelChoice(row.model, row.reasoning)


def message_choice_fields(choice: ModelChoice) -> dict[str, Any]:
    """The reasoning flag for an assistant ``Message`` (findings C15).

    ``messages.model`` is the model the provider reported, set by the orchestrator;
    ``messages.reasoning`` is the conversation's switch.
    """
    return {"reasoning": choice.reasoning}


def workspace_default_choice(
    settings: Settings, ent: ModelEntitlement, workspace: ModelChoice
) -> ModelChoice | None:
    """The workspace's default model and reasoning, if the tenant may use them now.

    Reasoning is dropped for a model without a switch. A default the tenant can no
    longer use (disabled since, or external without the entitlement) gives way to the
    EU fallback (findings C1), which is never an external model; None when the tenant
    has no EU model either.
    """
    model = catalogue.entry(settings, workspace.model)
    if model is not None and model.reasoning == "none":
        workspace = ModelChoice(workspace.model, False)
    try:
        check_choice(settings, ent, workspace)
    except ModelRefused:
        return eu_fallback_choice(settings, ent)
    return workspace


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
    choice = await conversation_choice(session, conversation_id)
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
    *,
    workspace_default: ModelChoice,
    model: str | None = None,
    reasoning: bool | None = None,
) -> Selection:
    """Check the user's choice for a new conversation, defaults from the workspace.

    ``model`` and ``reasoning`` are what the user asked for (None: not given).
    Without a model the workspace's default is checked (``workspace_default_choice``),
    with its reasoning switch (off when the EU fallback replaced it); with a model but
    without reasoning, the workspace's default switch applies where the model has one.
    Raises ``ModelRefused`` for a choice the tenant may not use. An external model
    whose tenant has reached the monthly spend cap falls back to the workspace default
    model, or to the EU fallback when that default is external too, keeping reasoning
    on only where the fallback has a switch; the fallback is audited
    (``model.fallback``) and the selection carries the user-facing notice.
    """
    ent = await load_entitlement(session, tenant_id)
    default = workspace_default_choice(settings, ent, workspace_default)
    if model is None:
        if default is None:
            raise ModelRefused("model_not_enabled")
        model = default.model
        if reasoning is None:
            reasoning = default.reasoning  # off when the EU fallback replaced the default
    if reasoning is None:
        entry = catalogue.entry(settings, model)
        reasoning = workspace_default.reasoning and entry is not None and entry.reasoning != "none"
    choice = ModelChoice(model, reasoning)
    checked = check_choice(settings, ent, choice)
    if not (checked.external and await cap_reached(session, settings, tenant_id, ent)):
        return Selection(choice)
    fallback_model = catalogue.entry(settings, default.model) if default else None
    if fallback_model is not None and fallback_model.external:
        default = eu_fallback_choice(settings, ent)
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
