"""P1c-14 (a): a reviewer withdraws a whole site.

- ``sites.status`` gains ``withdrawn``: the site is retired. It is never crawled again
  (scheduled crawls, "crawl now" and a queued crawl all need ``approved``) and its pages
  are withdrawn by the per-page ``withdraw_source`` job (``app.content.sites``).
- ``sites.withdrawn_at`` and ``sites.withdrawal_reason``: when and why; a check
  constraint requires both on a withdrawn site, as on a withdrawn source (revision 0013).

The app role already reads, inserts and updates ``sites`` (revision 0024); no grant
changes. The downgrade turns a withdrawn site into a rejected one (the nearest Phase 1b
state that is never crawled), keeping the reason as its review note.

Phase 1c Group D numbers its revisions from 0060 so that Groups A to C can use the
numbers after 0041 in parallel; the integration step re-parents if needed.

Revision ID: 0060
Revises: 0041
Create Date: 2026-10-23 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sites", sa.Column("withdrawal_reason", sa.Text(), nullable=True))
    op.drop_constraint(op.f("ck_sites_status_valid"), "sites", type_="check")
    op.create_check_constraint(
        op.f("ck_sites_status_valid"),
        "sites",
        "status IN ('proposed', 'approved', 'rejected', 'withdrawn')",
    )
    op.create_check_constraint(
        op.f("ck_sites_withdrawal_recorded"),
        "sites",
        "status <> 'withdrawn' OR (withdrawn_at IS NOT NULL "
        "AND length(btrim(coalesce(withdrawal_reason, ''))) > 0)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_sites_withdrawal_recorded"), "sites", type_="check")
    op.execute(
        "UPDATE sites SET status = 'rejected', next_crawl_at = NULL, "
        "review_note = coalesce(withdrawal_reason, review_note) WHERE status = 'withdrawn'"
    )
    op.drop_constraint(op.f("ck_sites_status_valid"), "sites", type_="check")
    op.create_check_constraint(
        op.f("ck_sites_status_valid"), "sites", "status IN ('proposed', 'approved', 'rejected')"
    )
    op.drop_column("sites", "withdrawal_reason")
    op.drop_column("sites", "withdrawn_at")
