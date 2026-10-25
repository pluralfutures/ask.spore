"""The tenant admin's usage section (P2A-05; architecture §7.2).

Built from the tenant's own ``chat.query`` audit events and ``usage_ledger`` rows, read in
the request's tenant-scoped transaction (RLS scopes every row; each query also names the
tenant). Counts only: questions per UTC day by answer mode, distinct active users per
day, the ten most cited sources by title and publisher, and, for a tenant with the
external-models entitlement, month-to-date tokens and cost per model. Nothing here
returns query text, a conversation or message ID, a user ID or a per-user figure.

Top sources come from the events' ``cited_source_ids`` rather than ``citations``: the
audit trail is kept 12 months while citations go with the chat history (30 days at
most, none for a tenant that keeps no history), so the events give the same count for
every tenant over the whole period (findings §2, P2A-05).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    UsageActiveUsersOut,
    UsageModelCostOut,
    UsageOut,
    UsageQuestionsOut,
    UsageSourceOut,
)
from app.core.config import Settings
from app.llm import catalogue
from app.tenancy.models import TenantEntitlements
from app.usage.ledger import month_of
from app.usage.models import UsageLedger

USAGE_DAYS: Final = 30
TOP_SOURCES: Final = 10

_QUESTIONS = text(
    """
    SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
           coalesce(metadata->>'mode', 'unknown') AS mode,
           count(*) AS questions
    FROM audit_events
    WHERE tenant_id = :tenant_id AND event = 'chat.query' AND created_at >= :start
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
)
_ACTIVE_USERS = text(
    """
    SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
           count(DISTINCT actor_user_id) AS users
    FROM audit_events
    WHERE tenant_id = :tenant_id AND event = 'chat.query' AND created_at >= :start
      AND actor_user_id IS NOT NULL
    GROUP BY 1
    ORDER BY 1
    """
)
# One count per answer that cited the source (the event lists each source once).
_TOP_SOURCES = text(
    """
    WITH cited AS (
        SELECT DISTINCT e.id, s.source_id
        FROM audit_events e,
             jsonb_array_elements_text(
                 CASE WHEN jsonb_typeof(e.metadata->'cited_source_ids') = 'array'
                      THEN e.metadata->'cited_source_ids' ELSE '[]'::jsonb END
             ) AS s(source_id)
        WHERE e.tenant_id = :tenant_id AND e.event = 'chat.query' AND e.created_at >= :start
    )
    SELECT src.title, src.publisher, count(*) AS answers
    FROM cited JOIN sources src ON src.id::text = cited.source_id
    GROUP BY src.id, src.title, src.publisher
    ORDER BY answers DESC, src.title, src.id
    LIMIT :top
    """
)


def period(today: date | None = None) -> tuple[date, date]:
    """The last ``USAGE_DAYS`` UTC days, today included."""
    until = today or datetime.now(UTC).date()
    return until - timedelta(days=USAGE_DAYS - 1), until


async def tenant_usage(
    session: AsyncSession, settings: Settings, tenant_id: UUID, *, today: date | None = None
) -> UsageOut:
    since, until = period(today)
    params = {
        "tenant_id": tenant_id,
        "start": datetime.combine(since, time.min, UTC),
        "top": TOP_SOURCES,
    }
    questions = [
        UsageQuestionsOut(day=r.day, mode=r.mode, questions=r.questions)
        for r in await session.execute(_QUESTIONS, params)
    ]
    active = [
        UsageActiveUsersOut(day=r.day, users=r.users)
        for r in await session.execute(_ACTIVE_USERS, params)
    ]
    sources = [
        UsageSourceOut(title=r.title, publisher=r.publisher, answers=r.answers)
        for r in await session.execute(_TOP_SOURCES, params)
    ]
    entitlements = await session.get(TenantEntitlements, tenant_id)
    cost_month: str | None = None
    costs: list[UsageModelCostOut] | None = None
    if entitlements is not None and entitlements.external_models_enabled:
        month = month_of()
        cost_month = month.strftime("%Y-%m")
        rows = await session.scalars(
            select(UsageLedger)
            .where(UsageLedger.tenant_id == tenant_id, UsageLedger.month == month)
            .order_by(UsageLedger.model)
        )
        costs = []
        for row in rows:
            entry = catalogue.entry(settings, row.model)
            costs.append(
                UsageModelCostOut(
                    model=row.model,
                    display_name=entry.display_name if entry else row.model,
                    external=entry.external if entry else False,
                    tokens_in=row.tokens_in,
                    tokens_out=row.tokens_out,
                    cost_cents=row.cost_cents,
                )
            )
    return UsageOut(
        since=since,
        until=until,
        questions=questions,
        active_users=active,
        top_sources=sources,
        cost_month=cost_month,
        costs=costs,
    )
