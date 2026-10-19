"""Usage ledger and spend notices. Mirrors alembic revision 0009; the migration is
authoritative."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UsageLedger(Base):
    """Tokens and cost per tenant, month (first day, UTC) and catalogue model."""

    __tablename__ = "usage_ledger"
    __table_args__ = (
        CheckConstraint("month = date_trunc('month', month)::date", name="first_of_month"),
        CheckConstraint(
            "tokens_in >= 0 AND tokens_out >= 0 AND cost_cents >= 0", name="non_negative"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    tokens_in: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    tokens_out: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    # Euro cents, fractional: priced from the catalogue at the time of the call.
    cost_cents: Mapped[Decimal] = mapped_column(Numeric(16, 6), server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SpendNotice(Base):
    """An external spend threshold (80 or 100 percent) already notified this month."""

    __tablename__ = "spend_notices"
    __table_args__ = (CheckConstraint("threshold IN (80, 100)", name="threshold"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    threshold: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
