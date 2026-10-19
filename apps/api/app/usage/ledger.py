"""Usage ledger and the external spend cap (P1a-10).

Every answer and query rewrite adds its tokens, priced from the catalogue in euro cents
(USD prices converted at ``[pricing] usd_to_eur``), to ``usage_ledger`` for the
tenant, month and model, in the same transaction that stores the message. External
models (OpenRouter) count towards the tenant's monthly ``external_spend_cap_cents``:

- at 80 percent an operator notice ``spend.cap_80`` is written, once per month;
- at 100 percent an operator notice ``spend.cap_100`` is written, once per month, and
  ``cap_reached`` turns true: new conversations on external models fall back to the
  default model (``app.chat.selection.choose_for_new_conversation``) and existing ones
  are refused before any call (``app.chat.selection.authorize``).

Months are calendar months in UTC. The check runs before a call and the cost is known
only after it, so concurrent answers can overshoot the cap by what is in flight.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Table, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.llm import catalogue
from app.llm.mistral import Usage
from app.operator.models import OperatorNotice
from app.tenancy.entitlements import ModelEntitlement
from app.usage.models import SpendNotice, UsageLedger

THRESHOLDS = (80, 100)


def month_of(now: datetime | None = None) -> date:
    """The ledger month: the first day of ``now``'s calendar month in UTC."""
    return (now or datetime.now(UTC)).astimezone(UTC).date().replace(day=1)


async def record_usage(
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    usage: Sequence[tuple[str, Usage]],
    entitlement: ModelEntitlement | None,
    *,
    now: datetime | None = None,
) -> None:
    """Add ``(model, usage)`` pairs to the ledger; notify spend thresholds if external."""
    month = month_of(now)
    totals: dict[str, tuple[int, int]] = {}
    for model, used in usage:
        tokens_in, tokens_out = totals.get(model, (0, 0))
        totals[model] = (tokens_in + used.tokens_in, tokens_out + used.tokens_out)
    external = False
    for model, (tokens_in, tokens_out) in totals.items():
        entry = catalogue.entry(settings, model)
        cost = catalogue.cost_cents(settings, entry, tokens_in, tokens_out) if entry else Decimal(0)
        external = external or (entry is not None and entry.external)
        stmt = pg_insert(UsageLedger).values(
            tenant_id=tenant_id,
            month=month,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_cents=cost,
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[UsageLedger.tenant_id, UsageLedger.month, UsageLedger.model],
                set_={
                    "tokens_in": UsageLedger.tokens_in + stmt.excluded.tokens_in,
                    "tokens_out": UsageLedger.tokens_out + stmt.excluded.tokens_out,
                    "cost_cents": UsageLedger.cost_cents + stmt.excluded.cost_cents,
                    "updated_at": func.now(),
                },
            )
        )
    if external and entitlement is not None:
        await notify_thresholds(session, settings, tenant_id, entitlement, month)


async def external_spend_cents(
    session: AsyncSession, settings: Settings, tenant_id: uuid.UUID, month: date
) -> Decimal:
    spent = await session.scalar(
        select(func.coalesce(func.sum(UsageLedger.cost_cents), 0)).where(
            UsageLedger.tenant_id == tenant_id,
            UsageLedger.month == month,
            UsageLedger.model.in_(catalogue.external_ids(settings)),
        )
    )
    return Decimal(spent or 0)


async def cap_reached(
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    entitlement: ModelEntitlement,
    *,
    now: datetime | None = None,
) -> bool:
    """True when this month's external spend has reached the cap (no cap: reached)."""
    cap = entitlement.external_spend_cap_cents
    if cap is None:
        return True
    return await external_spend_cents(session, settings, tenant_id, month_of(now)) >= cap


async def notify_thresholds(
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    entitlement: ModelEntitlement,
    month: date,
) -> None:
    """Write each reached threshold's operator notice, once per tenant and month."""
    cap = entitlement.external_spend_cap_cents
    if not cap or cap <= 0:
        return  # no cap, or a zero cap that refuses every external call anyway
    spent = await external_spend_cents(session, settings, tenant_id, month)
    for threshold in THRESHOLDS:
        if spent * 100 < cap * threshold:
            continue
        first = await session.scalar(
            pg_insert(SpendNotice)
            .values(tenant_id=tenant_id, month=month, threshold=threshold)
            .on_conflict_do_nothing()
            .returning(SpendNotice.threshold)
        )
        if first is None:
            continue  # already notified this month
        # A Core insert on the table with the ID set here, so no RETURNING is added: the
        # application role may insert notices but not read them.
        notices: Table = OperatorNotice.__table__  # type: ignore[assignment]
        await session.execute(
            insert(notices).values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                kind=f"spend.cap_{threshold}",
                metadata={
                    "month": month.strftime("%Y-%m"),
                    "threshold_percent": threshold,
                    "cap_cents": cap,
                    "spent_cents": int(spent),
                },
            )
        )
