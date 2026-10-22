"""P1b-15 d: reasoning tokens in the usage ledger.

``usage_ledger.reasoning_tokens``: of ``tokens_out``, how many the model spent on hidden
reasoning, where the provider reports them (``completion_tokens_details``), summed per
tenant, month and model like the other counts. A count only; non-negative and never
more than ``tokens_out``. Existing rows start at 0 (not recorded before).

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-22 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usage_ledger",
        sa.Column("reasoning_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_usage_ledger_reasoning_within_output"),
        "usage_ledger",
        "reasoning_tokens >= 0 AND reasoning_tokens <= tokens_out",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_usage_ledger_reasoning_within_output"), "usage_ledger", type_="check"
    )
    op.drop_column("usage_ledger", "reasoning_tokens")
