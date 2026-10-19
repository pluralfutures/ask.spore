"""P1a-10: usage ledger and external spend notices.

- ``usage_ledger(tenant_id, month, model, tokens_in, tokens_out, cost_cents)``: tokens
  and cost per tenant, calendar month (UTC, first day) and catalogue model, added to
  after every answer and query rewrite. ``cost_cents`` is euro cents priced from the
  catalogue at the time of the call, kept fractional (``numeric``) so many small calls
  do not round to nothing. Keyed ``(tenant_id, month, model)``, so the primary key is
  the ``tenant_id``-first index; forced RLS from this first migration. The application
  role may read, insert and update (upsert); it may not delete.
- ``spend_notices(tenant_id, month, threshold)``: which external spend thresholds (80
  and 100 percent of ``external_spend_cap_cents``) have already raised an operator
  notice this month, so each is raised once. Tenant-scoped like the ledger.
- ``operator_notices``: the application role gets INSERT (revision 0006 left it
  without), to write the spend notices. P1a-07 (Group B) grants the same privilege;
  GRANT is idempotent in PostgreSQL, so either order works. The downgrade does not
  revoke it, because P1a-07 also relies on it: whichever revision granted first keeps
  the grant until its own downgrade.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

APP_ROLE = "askspore_app"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_isolation(table: str) -> None:
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})"
    )


def upgrade() -> None:
    op.create_table(
        "usage_ledger",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("tokens_in", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_out", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cost_cents",
            sa.Numeric(precision=16, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "month = date_trunc('month', month)::date", name=op.f("ck_usage_ledger_first_of_month")
        ),
        sa.CheckConstraint(
            "tokens_in >= 0 AND tokens_out >= 0 AND cost_cents >= 0",
            name=op.f("ck_usage_ledger_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_usage_ledger_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "month", "model", name=op.f("pk_usage_ledger")),
    )
    _tenant_isolation("usage_ledger")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON usage_ledger TO {APP_ROLE}")

    op.create_table(
        "spend_notices",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("threshold IN (80, 100)", name=op.f("ck_spend_notices_threshold")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_spend_notices_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "month", "threshold", name=op.f("pk_spend_notices")),
    )
    _tenant_isolation("spend_notices")
    op.execute(f"GRANT SELECT, INSERT ON spend_notices TO {APP_ROLE}")

    # Idempotent; shared with P1a-07 (see the module docstring).
    op.execute(f"GRANT INSERT ON operator_notices TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("spend_notices")
    op.drop_table("usage_ledger")
