"""The retention purge (P1b-14): deletes what is past its retention, tenant by tenant.

Read-time expiry stays the first layer (every read route hides a conversation past
``expires_at``); this job deletes the rows themselves:

- conversations past ``expires_at``, with their messages, citations and feedback;
- ``revoked_sessions`` rows past their token's own expiry (the token is refused anyway);
- ``downloads`` rows older than ``[retention] downloads_days`` (owner decision of Oct 21,
  2026: 90 days). The ``download`` audit events stay, as every audit event does.

It runs as ``askspore_retention`` (revision 0040): the role lists tenant IDs, and every
deletion runs in a transaction scoped to one tenant (``app.tenant_id``), so the
tenant tables' RLS policies decide what it can reach. One transaction per tenant: a
failure leaves the other tenants' purges in place. The job reports counts only.

A ``purge_retention`` job runs it on the P1b-02 queue: the worker queues one a day
(``schedule_purge``), and ``ask-spore purge --run`` queues one on demand; ``ask-spore
purge --dry-run`` counts what would go, deleting nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, fields
from datetime import timedelta
from typing import Any, Final

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import RevokedSession
from app.chat.models import Citation, Conversation, Feedback, Message
from app.content.jobs import Job, enqueue
from app.core.db import RETENTION_ROLE, role_session, tenant_role_session
from app.files.models import Download
from app.tenancy.models import Tenant
from app.tenancy.retention import NO_HISTORY_WINDOW

PURGE_INTERVAL: Final = timedelta(days=1)


@dataclass(frozen=True)
class PurgeCounts:
    """Rows deleted (or, in a dry run, due) per table; counts only."""

    citations: int = 0
    feedback: int = 0
    messages: int = 0
    conversations: int = 0
    revoked_sessions: int = 0
    downloads: int = 0

    @property
    def total(self) -> int:
        return sum(self.as_dict().values())

    def as_dict(self) -> dict[str, int]:
        return {f.name: int(getattr(self, f.name)) for f in fields(self)}


@dataclass(frozen=True)
class TenantPurge:
    tenant_id: uuid.UUID
    counts: PurgeCounts


def _targets(downloads_days: int) -> dict[str, tuple[Any, Any]]:
    """Per table, in deletion order (children first): the model and its filter."""
    # A conversation younger than the "no history" window may still be streaming its
    # one answer; it is deleted when that stream closes, or by the next run.
    is_expired = (Conversation.expires_at <= func.now()) & (
        Conversation.created_at <= func.now() - NO_HISTORY_WINDOW
    )
    expired = select(Conversation.id).where(is_expired)
    expired_messages = select(Message.id).where(Message.conversation_id.in_(expired))
    return {
        "citations": (Citation, Citation.message_id.in_(expired_messages)),
        "feedback": (Feedback, Feedback.message_id.in_(expired_messages)),
        "messages": (Message, Message.conversation_id.in_(expired)),
        "conversations": (Conversation, is_expired),
        "revoked_sessions": (RevokedSession, RevokedSession.expires_at <= func.now()),
        "downloads": (
            Download,
            Download.created_at < func.now() - func.make_interval(0, 0, 0, downloads_days),
        ),
    }


async def _purge_tenant(session: AsyncSession, downloads_days: int, dry_run: bool) -> PurgeCounts:
    counts: dict[str, int] = {}
    for table, (model, condition) in _targets(downloads_days).items():
        if dry_run:
            counts[table] = int(
                await session.scalar(select(func.count()).select_from(model).where(condition)) or 0
            )
        else:
            result = await session.execute(
                delete(model).where(condition).execution_options(synchronize_session=False)
            )
            counts[table] = int(getattr(result, "rowcount", 0) or 0)
    return PurgeCounts(**counts)


async def purge_retention(
    factory: async_sessionmaker[AsyncSession], *, downloads_days: int, dry_run: bool = False
) -> list[TenantPurge]:
    """Delete (or with ``dry_run`` count) every tenant's expired rows; counts per tenant."""
    if downloads_days < 1:
        raise ValueError("downloads_days must be at least 1")
    async with role_session(factory, RETENTION_ROLE) as session:
        tenant_ids = list(await session.scalars(select(Tenant.id).order_by(Tenant.id)))
    purged: list[TenantPurge] = []
    for tenant_id in tenant_ids:
        async with tenant_role_session(factory, RETENTION_ROLE, tenant_id) as session:
            counts = await _purge_tenant(session, downloads_days, dry_run)
        purged.append(TenantPurge(tenant_id, counts))
    return purged


async def schedule_purge(
    factory: async_sessionmaker[AsyncSession], *, interval: timedelta = PURGE_INTERVAL
) -> uuid.UUID | None:
    """Queue a ``purge_retention`` job unless one was queued within ``interval``.

    Run by the worker between jobs, so the purge runs about once a day; the ID of the
    job queued, or None."""
    async with factory() as session, session.begin():
        recent = await session.scalar(
            select(Job.id)
            .where(
                Job.type == "purge_retention",
                Job.created_at
                > func.now() - func.make_interval(0, 0, 0, 0, 0, 0, interval.total_seconds()),
            )
            .limit(1)
        )
        if recent is not None:
            return None
        return await enqueue(session, "purge_retention", {}, created_by=None, max_attempts=1)
