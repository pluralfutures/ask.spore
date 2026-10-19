"""P1a-07: tenant-name flag on saved workspace prompts.

A saved workspace prompt that names the tenant (display name, verified domains, its
users' names or emails) writes an operator notice and an audit event, in the same
tenant-scoped transaction as the save. Revision 0006 left ``operator_notices`` without
privileges for the application role on purpose; this revision grants INSERT only.
The ``tenant_isolation`` policy (forced) still applies, so the application can write a
notice for the request's tenant only, and it can read none: notices are the
operator's.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19 18:00:00
"""

from collections.abc import Sequence

from alembic import op

APP_ROLE = "askspore_app"

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(f"GRANT INSERT ON operator_notices TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT ON operator_notices FROM {APP_ROLE}")
