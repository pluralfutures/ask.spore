"""Chat-history retention per tenant (P1a-13; architecture §7.2).

Retention is 30 days at most (CLAUDE.md). A tenant admin may shorten it to between 0
and 30 days (``tenant_settings.retention_days``, capped by a check constraint too); a
tenant without a setting keeps the 30-day maximum. A new conversation expires after
its tenant's retention. Shortening also brings forward the expiry of existing
conversations, which read routes apply at read time and the retention purge
(``app.tenancy.purge``, P1b-14) then deletes;
lengthening again applies to new conversations only, so nothing already due to expire
is kept longer than the setting in force when it was due.

0 days is "no history" (P1b-14): a conversation is created already expired, takes one
question, and is deleted when its answer's stream closes (``app.chat.orchestrator``).

Everything here runs in the caller's tenant-scoped transaction (RLS).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import Conversation
from app.tenancy.models import MAX_RETENTION_DAYS, TenantSettings

MIN_RETENTION_DAYS = 0  # "no history" (P1b-14)
# How long a "no history" conversation waits for its one question and its answer; the
# retention purge leaves conversations this young alone, so it never deletes one whose
# answer is still streaming.
NO_HISTORY_WINDOW = timedelta(minutes=10)


async def retention_days(session: AsyncSession) -> int:
    """The session tenant's retention in days; the maximum without a setting."""
    days = await session.scalar(select(TenantSettings.retention_days))
    return MAX_RETENTION_DAYS if days is None else min(days, MAX_RETENTION_DAYS)


def expiry(days: int) -> Any:
    """``now() + days``, as a SQL expression for ``conversations.expires_at``."""
    return func.now() + func.make_interval(0, 0, 0, min(days, MAX_RETENTION_DAYS))


async def set_retention(session: AsyncSession, tenant_id: uuid.UUID, days: int) -> int:
    """Store ``days`` (0 to 30) and expire existing conversations accordingly.

    Returns how many conversations had their expiry brought forward.
    """
    if not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS:
        raise ValueError("retention must be between 0 and 30 days")
    upsert = insert(TenantSettings).values(tenant_id=tenant_id, retention_days=days)
    await session.execute(
        upsert.on_conflict_do_update(
            index_elements=["tenant_id"],
            set_={"retention_days": upsert.excluded.retention_days, "updated_at": func.now()},
        )
    )
    cutoff = Conversation.created_at + func.make_interval(0, 0, 0, days)
    shortened = await session.execute(
        update(Conversation)
        .where(Conversation.expires_at > cutoff)
        .values(expires_at=cutoff)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(shortened, "rowcount", 0) or 0)
