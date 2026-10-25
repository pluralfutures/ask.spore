"""P2A-01: a content reviewer pauses an ingested source.

- ``sources.status`` gains ``paused``: the source stays in the register and its RAGFlow
  documents stay in place, disabled (``enabled: 0``), so no tenant retrieves, lists or
  downloads it; resuming needs no re-parse (phase-2a-findings.md, "P2A-00 probe").
- ``sources.paused_at``, ``paused_by`` and ``pause_reason``: when, by whom and why. A check
  constraint requires all three on a paused source and none on any other, so a resume
  clears them; the audit trail keeps the history (``source.paused``, ``source.resumed``).

The app role already reads and updates ``sources`` (revision 0001); no grant changes. The
downgrade sets a paused source back to ``ingested``: its RAGFlow documents stay disabled
until a person re-enables them (``datasets sync`` reports the mismatch).

Phase 2A Group A numbers its revision 0070 so that Groups B to E can use the numbers
after 0060 in parallel; the integration step re-parents if needed.

Revision ID: 0070
Revises: 0060
Create Date: 2026-10-25 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = "('proposed', 'approved', 'ingested', 'failed', 'withdrawn', 'rejected')"
NEW_STATUSES = "('proposed', 'approved', 'ingested', 'failed', 'withdrawn', 'rejected', 'paused')"
PAUSE_RECORDED = (
    "CASE WHEN status = 'paused' THEN paused_at IS NOT NULL AND paused_by IS NOT NULL "
    "AND length(btrim(coalesce(pause_reason, ''))) > 0 "
    "ELSE paused_at IS NULL AND paused_by IS NULL AND pause_reason IS NULL END"
)


def upgrade() -> None:
    op.add_column("sources", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("paused_by", sa.UUID(), nullable=True))
    op.add_column("sources", sa.Column("pause_reason", sa.Text(), nullable=True))
    op.drop_constraint(op.f("ck_sources_status_valid"), "sources", type_="check")
    op.create_check_constraint(
        op.f("ck_sources_status_valid"), "sources", f"status IN {NEW_STATUSES}"
    )
    op.create_check_constraint(op.f("ck_sources_pause_recorded"), "sources", PAUSE_RECORDED)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_sources_pause_recorded"), "sources", type_="check")
    op.execute("UPDATE sources SET status = 'ingested' WHERE status = 'paused'")
    op.drop_constraint(op.f("ck_sources_status_valid"), "sources", type_="check")
    op.create_check_constraint(
        op.f("ck_sources_status_valid"), "sources", f"status IN {OLD_STATUSES}"
    )
    op.drop_column("sources", "pause_reason")
    op.drop_column("sources", "paused_by")
    op.drop_column("sources", "paused_at")
