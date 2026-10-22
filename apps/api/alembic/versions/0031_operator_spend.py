"""P1b-12: the operator console reads month-to-date spend and token usage.

``askspore_operator`` (revision 0006) gains read access to ``usage_ledger`` and
``spend_notices`` (revision 0009), through an ``operator_console`` policy for that
role only, as on the other tables the console reads. Both are tenant-scoped tables
with forced RLS; their ``tenant_isolation`` policies are unchanged, so the
application role still sees only its own tenant's rows. The ledger holds token counts
and cost per tenant, month and model: no query text exists in it to read.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-22 12:00:00
"""

from collections.abc import Sequence

from alembic import op

OPERATOR_ROLE = "askspore_operator"
TABLES = ("usage_ledger", "spend_notices")

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {OPERATOR_ROLE}")
        op.execute(
            f"CREATE POLICY operator_console ON {table} FOR SELECT TO {OPERATOR_ROLE} USING (true)"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY operator_console ON {table}")
        op.execute(f"REVOKE SELECT ON {table} FROM {OPERATOR_ROLE}")
