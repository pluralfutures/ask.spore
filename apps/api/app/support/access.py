"""Time-boxed support access (P2A-08; architecture §7.4; consent notice v1 §1 and §7;
``policy-access-control.md`` rule 7).

A tenant admin grants the platform operators read access to one scope of their tenant,
``settings`` or one of their own conversations, for 15 minutes to 4 hours, with a note,
and can revoke it at once. The operator sees the tenant's open grants on its console
page and reads the granted scope through dedicated routes. Every such read:

- runs as ``askspore_support`` (revision 0065) with ``app.tenant_id`` set to the tenant
  named in the path, so RLS keeps it inside that tenant, and the role's restrictive
  ``support_grant`` policies show a conversation only while an open grant names it and
  the settings only while an open ``settings`` grant exists;
- first finds the grant by ID in that tenant, open (not revoked, not closed, not past
  ``expires_at``), of the route's scope and, for a conversation, naming the
  conversation in the path; anything else is ``SupportNotFound`` (404), whatever the
  reason, so a refusal says nothing about other grants or conversations;
- writes ``operator.support_viewed`` (grant ID, scope, operator ID, never content) in the
  same transaction, so no read happens without its audit event.

The operator never writes through a grant (the role can insert its audit event and
nothing else), never sees another conversation, and keeps their own session and
identity: there is no impersonation. Nothing read here reaches a log line, an exception
or an audit event: logs carry the tenant and grant IDs and a code only.

Expiry is checked at read time (here) and by the daily purge job, which closes expired
grants (``app.tenancy.purge``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, func, literal_column, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.schemas import (
    OperatorSupportGrantOut,
    SupportCitationOut,
    SupportConversationOut,
    SupportGrantIn,
    SupportGrantOut,
    SupportMessageOut,
    SupportSettingsOut,
    SupportWorkspaceOut,
)
from app.audit.models import AuditEvent
from app.audit.writer import record
from app.chat.models import Citation, Conversation, Message
from app.content.models import Source
from app.core.db import SUPPORT_ROLE, tenant_role_session
from app.core.logging import log
from app.support.models import SupportGrant
from app.tenancy.models import MAX_RETENTION_DAYS, TenantSettings
from app.tenancy.workspaces import Workspace

VIEWED_EVENT: Final = "operator.support_viewed"
MAX_LISTED: Final = 200


class SupportNotFound(Exception):
    """No open grant of this tenant covers the read. Carries no detail."""


class GrantRefused(Exception):
    """A tenant admin's grant or revocation was refused; ``code`` says why."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _is_open(now: datetime) -> list[ColumnElement[bool]]:
    return [
        SupportGrant.revoked_at.is_(None),
        SupportGrant.closed_at.is_(None),
        SupportGrant.expires_at > now,
    ]


def grant_state(grant: SupportGrant, views: int, now: datetime) -> str:
    """``revoked`` before ``expired`` before ``used`` (read at least once) before ``open``."""
    if grant.revoked_at is not None:
        return "revoked"
    if grant.closed_at is not None or grant.expires_at <= now:
        return "expired"
    return "used" if views else "open"


# --- the tenant admin's side (application role, tenant-scoped session) ---------------------


async def create_grant(
    session: AsyncSession, *, tenant_id: UUID, admin_user_id: UUID, body: SupportGrantIn
) -> SupportGrant:
    if body.scope == "conversation":
        if body.conversation_id is None:
            raise GrantRefused("conversation_required")
        # One of the admin's own live conversations ("chosen from their own list").
        owned = await session.scalar(
            select(Conversation.id).where(
                Conversation.id == body.conversation_id,
                Conversation.user_id == admin_user_id,
                Conversation.expires_at > func.now(),
            )
        )
        if owned is None:
            raise GrantRefused("conversation_not_found")
    elif body.conversation_id is not None:
        raise GrantRefused("conversation_not_allowed")
    now = await session.scalar(select(func.now()))
    if now is None:
        raise AssertionError("now() returns a value")
    grant = SupportGrant(
        tenant_id=tenant_id,
        scope=body.scope,
        conversation_id=body.conversation_id,
        duration_minutes=body.duration_minutes,
        note=body.note.strip(),
        created_at=now,
        expires_at=now + timedelta(minutes=body.duration_minutes),
    )
    if not grant.note:
        raise GrantRefused("note_required")
    session.add(grant)
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=admin_user_id,
        event="tenant_admin.support_granted",
        metadata={
            "grant_id": str(grant.id),
            "scope": grant.scope,
            "conversation_id": str(grant.conversation_id) if grant.conversation_id else None,
            "duration_minutes": grant.duration_minutes,
        },
    )
    log("tenant_admin.support_granted", tenant_id=str(tenant_id), grant_id=str(grant.id))
    return grant


async def revoke_grant(
    session: AsyncSession, *, tenant_id: UUID, admin_user_id: UUID, grant_id: UUID
) -> SupportGrant:
    grant = await session.scalar(
        select(SupportGrant)
        .where(SupportGrant.id == grant_id, SupportGrant.tenant_id == tenant_id)
        .with_for_update()
    )
    if grant is None:
        raise SupportNotFound
    now = await session.scalar(select(func.now()))
    if now is None or grant.revoked_at is not None or grant.closed_at is not None:
        raise GrantRefused("not_open")
    if grant.expires_at <= now:
        raise GrantRefused("not_open")
    grant.revoked_at = now
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=admin_user_id,
        event="tenant_admin.support_revoked",
        metadata={"grant_id": str(grant.id), "scope": grant.scope},
    )
    log("tenant_admin.support_revoked", tenant_id=str(tenant_id), grant_id=str(grant.id))
    return grant


@dataclass(frozen=True)
class _Views:
    count: int
    last: datetime | None


async def _views(session: AsyncSession, tenant_id: UUID) -> dict[str, _Views]:
    grant_id: ColumnElement[str] = literal_column("metadata->>'grant_id'")
    rows = await session.execute(
        select(
            grant_id.label("grant_id"),
            func.count().label("views"),
            func.max(AuditEvent.created_at).label("last"),
        )
        .where(AuditEvent.tenant_id == tenant_id, AuditEvent.event == VIEWED_EVENT)
        .group_by(grant_id)
    )
    return {str(r.grant_id): _Views(int(r.views), r.last) for r in rows}


async def list_grants(session: AsyncSession, tenant_id: UUID) -> list[SupportGrantOut]:
    """The tenant's grants, newest first, with their state and the operator's reads."""
    now = await session.scalar(select(func.now())) or datetime.now(UTC)
    grants = list(
        await session.scalars(
            select(SupportGrant)
            .where(SupportGrant.tenant_id == tenant_id)
            .order_by(SupportGrant.created_at.desc(), SupportGrant.id)
            .limit(MAX_LISTED)
        )
    )
    views = await _views(session, tenant_id)
    ids = [g.conversation_id for g in grants if g.conversation_id is not None]
    titles = {
        r.id: r.title
        for r in await session.execute(
            select(Conversation.id, Conversation.title).where(Conversation.id.in_(ids))
        )
    }
    out = []
    for grant in grants:
        seen = views.get(str(grant.id), _Views(0, None))
        out.append(
            SupportGrantOut(
                id=grant.id,
                scope=grant.scope,  # type: ignore[arg-type]
                conversation_id=grant.conversation_id,
                conversation_title=titles.get(grant.conversation_id)
                if grant.conversation_id
                else None,
                duration_minutes=grant.duration_minutes,
                note=grant.note,
                created_at=grant.created_at,
                expires_at=grant.expires_at,
                revoked_at=grant.revoked_at,
                state=grant_state(grant, seen.count, now),  # type: ignore[arg-type]
                views=seen.count,
                last_viewed_at=seen.last,
            )
        )
    return out


# --- the operator's side (askspore_support, scoped to the path's tenant) -------------------


async def open_grants(
    factory: async_sessionmaker[AsyncSession], tenant_id: UUID
) -> list[OperatorSupportGrantOut]:
    async with tenant_role_session(factory, SUPPORT_ROLE, tenant_id) as session:
        now = await session.scalar(select(func.now())) or datetime.now(UTC)
        rows = await session.execute(
            select(
                SupportGrant.id,
                SupportGrant.scope,
                SupportGrant.conversation_id,
                SupportGrant.note,
                SupportGrant.created_at,
                SupportGrant.expires_at,
            )
            .where(SupportGrant.tenant_id == tenant_id, *_is_open(now))
            .order_by(SupportGrant.expires_at, SupportGrant.id)
        )
        return [
            OperatorSupportGrantOut(
                id=r.id,
                scope=r.scope,
                conversation_id=r.conversation_id,
                note=r.note,
                created_at=r.created_at,
                expires_at=r.expires_at,
            )
            for r in rows
        ]


@dataclass(frozen=True)
class _OpenGrant:
    id: UUID
    scope: str
    conversation_id: UUID | None
    expires_at: datetime


async def _open_grant(
    session: AsyncSession, tenant_id: UUID, grant_id: UUID, scope: str
) -> _OpenGrant:
    """The open grant ``grant_id`` of ``tenant_id`` with ``scope``, or SupportNotFound.
    Checked on every call; the database's ``support_grant`` policies check it again."""
    now = await session.scalar(select(func.now()))
    if now is None:
        raise SupportNotFound
    row = (
        await session.execute(
            select(
                SupportGrant.id,
                SupportGrant.scope,
                SupportGrant.conversation_id,
                SupportGrant.expires_at,
            ).where(
                SupportGrant.id == grant_id,
                SupportGrant.tenant_id == tenant_id,
                SupportGrant.scope == scope,
                *_is_open(now),
            )
        )
    ).one_or_none()
    if row is None:
        raise SupportNotFound
    return _OpenGrant(row.id, row.scope, row.conversation_id, row.expires_at)


async def _viewed(
    session: AsyncSession, tenant_id: UUID, operator_id: UUID, grant: _OpenGrant
) -> None:
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=None,
        event="operator.support_viewed",
        metadata={
            "operator_id": str(operator_id),
            "grant_id": str(grant.id),
            "scope": grant.scope,
            "conversation_id": str(grant.conversation_id) if grant.conversation_id else None,
        },
    )
    log(VIEWED_EVENT, tenant_id=str(tenant_id), grant_id=str(grant.id), status="ok")


def refused(tenant_id: UUID) -> None:
    log("operator.support_refused", tenant_id=str(tenant_id), error_code="no_open_grant")


async def view_conversation(
    factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    grant_id: UUID,
    conversation_id: UUID,
    operator_id: UUID,
) -> SupportConversationOut:
    async with tenant_role_session(factory, SUPPORT_ROLE, tenant_id) as session:
        grant = await _open_grant(session, tenant_id, grant_id, "conversation")
        if grant.conversation_id != conversation_id:
            raise SupportNotFound
        conversation = (
            await session.execute(
                select(
                    Conversation.title,
                    Conversation.workspace_id,
                    Conversation.mode,
                    Conversation.model,
                    Conversation.created_at,
                ).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                    Conversation.expires_at > func.now(),  # read-time expiry, as for its user
                )
            )
        ).one_or_none()
        if conversation is None:
            raise SupportNotFound
        messages = (
            await session.execute(
                select(
                    Message.id,
                    Message.role,
                    Message.content,
                    Message.created_at,
                    Message.outcome,
                    Message.truncated,
                    Message.partial,
                )
                .where(Message.conversation_id == conversation_id, Message.tenant_id == tenant_id)
                .order_by(Message.created_at, Message.role.desc())
            )
        ).all()
        cited = await session.execute(
            select(
                Citation.message_id,
                Citation.marker,
                Citation.page_or_slide,
                Citation.excerpt,
                Citation.superseded_at,
                Citation.withdrawn_at,
                Source.title,
                Source.publisher,
                Source.published_on,
                Source.type,
                Source.canonical_url,
            )
            .join(Source, Source.id == Citation.source_id)
            .where(Citation.message_id.in_([m.id for m in messages]))
            .order_by(Citation.marker)
        )
        by_message: dict[UUID, list[SupportCitationOut]] = {}
        for c in cited:
            by_message.setdefault(c.message_id, []).append(
                SupportCitationOut(
                    marker=c.marker,
                    title=c.title,
                    publisher=c.publisher,
                    published_on=c.published_on,
                    page_or_slide=c.page_or_slide,
                    type=c.type,
                    canonical_url=c.canonical_url,
                    excerpt=c.excerpt,
                    superseded=c.superseded_at is not None,
                    withdrawn=c.withdrawn_at is not None,
                )
            )
        workspace_name = await session.scalar(
            select(Workspace.name).where(Workspace.id == conversation.workspace_id)
        )
        out = SupportConversationOut(
            grant_id=grant.id,
            expires_at=grant.expires_at,
            title=conversation.title,
            workspace_name=workspace_name or "",
            mode=conversation.mode,
            model=conversation.model,
            created_at=conversation.created_at,
            messages=[
                SupportMessageOut(
                    role="assistant" if m.role == "assistant" else "user",
                    content=m.content,
                    created_at=m.created_at,
                    unsupported=m.outcome == "unsupported",
                    truncated=m.truncated,
                    partial=m.partial,
                    citations=by_message.get(m.id, []),
                )
                for m in messages
            ],
        )
        await _viewed(session, tenant_id, operator_id, grant)
        return out


_LATEST_PROMPTS = text(
    "SELECT DISTINCT ON (workspace_id) workspace_id, version, text FROM workspace_prompts "
    "WHERE tenant_id = :tenant_id ORDER BY workspace_id, version DESC"
)


async def view_settings(
    factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    grant_id: UUID,
    operator_id: UUID,
) -> SupportSettingsOut:
    async with tenant_role_session(factory, SUPPORT_ROLE, tenant_id) as session:
        grant = await _open_grant(session, tenant_id, grant_id, "settings")
        retention = await session.scalar(
            select(TenantSettings.retention_days).where(TenantSettings.tenant_id == tenant_id)
        )
        prompts = {
            r.workspace_id: (int(r.version), str(r.text))
            for r in await session.execute(_LATEST_PROMPTS, {"tenant_id": tenant_id})
        }
        workspaces = await session.execute(
            select(
                Workspace.id,
                Workspace.name,
                Workspace.slug,
                Workspace.default_mode,
                Workspace.default_model,
                Workspace.default_reasoning,
            )
            .where(Workspace.tenant_id == tenant_id)
            .order_by(Workspace.name, Workspace.slug)
        )
        out = SupportSettingsOut(
            grant_id=grant.id,
            expires_at=grant.expires_at,
            retention_days=MAX_RETENTION_DAYS if retention is None else retention,
            workspaces=[
                SupportWorkspaceOut(
                    name=w.name,
                    slug=w.slug,
                    default_mode=w.default_mode,
                    default_model=w.default_model,
                    default_reasoning=w.default_reasoning,
                    instructions_version=prompts[w.id][0] if w.id in prompts else None,
                    instructions=prompts[w.id][1] if w.id in prompts else None,
                )
                for w in workspaces
            ],
        )
        await _viewed(session, tenant_id, operator_id, grant)
        return out


# --- the daily purge (askspore_retention, scoped to one tenant) ----------------------------


async def close_expired(session: AsyncSession, tenant_id: UUID, *, dry_run: bool) -> int:
    """Close the tenant's grants past ``expires_at``; one ``support.grant_expired`` each."""
    expired = (
        SupportGrant.tenant_id == tenant_id,
        SupportGrant.closed_at.is_(None),
        SupportGrant.revoked_at.is_(None),
        SupportGrant.expires_at <= func.now(),
    )
    if dry_run:
        return int(
            await session.scalar(select(func.count()).select_from(SupportGrant).where(*expired))
            or 0
        )
    closed = list(
        await session.scalars(
            update(SupportGrant)
            .where(*expired)
            .values(closed_at=func.now())
            .returning(SupportGrant.id)
            .execution_options(synchronize_session=False)
        )
    )
    for grant_id in closed:
        await record(
            session,
            tenant_id=tenant_id,
            actor_user_id=None,
            event="support.grant_expired",
            metadata={"grant_id": str(grant_id)},
        )
    return len(closed)
