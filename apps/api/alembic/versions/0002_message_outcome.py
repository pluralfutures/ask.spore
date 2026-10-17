"""P0-14: record each assistant message's outcome.

``messages.outcome`` is ``answered`` (cited answer), ``unsupported`` (an answer with
no valid citation, flagged to the user) or ``abstained`` (nothing passed the
similarity threshold; no LLM call). NULL for user messages. Stored so a reloaded
conversation shows the same badge and empty state as the live stream.

``messages`` already has row-level security and a tenant_id-first index (0001);
adding a column changes neither.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17 23:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("outcome", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_messages_outcome_valid"),
        "messages",
        "(role = 'user' AND outcome IS NULL) OR "
        "(role = 'assistant' AND outcome IN ('answered', 'unsupported', 'abstained'))",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_messages_outcome_valid"), "messages", type_="check")
    op.drop_column("messages", "outcome")
