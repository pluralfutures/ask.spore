"""P1a-13: tenant admin pages: users, workspace defaults and retention.

- ``tenant_settings(tenant_id, retention_days, updated_at)``: what a tenant admin sets
  for their own tenant. ``retention_days`` is the chat-history retention, between 1 and
  30 days (CLAUDE.md: 30 days maximum; a tenant admin may shorten it, never lengthen
  it beyond 30, and the check constraint refuses more whoever writes). A tenant
  without a row has the 30-day maximum. Tenant-scoped: forced RLS, primary key
  ``tenant_id``. The application role may read, insert and update the retention.
- ``users``: the application role may now INSERT (a tenant admin invites a user, as
  ``invited``) and UPDATE ``role`` (it already updates ``status`` since revision 0005,
  which now also covers deactivation). Still no DELETE: users are deactivated.
- ``workspaces``: the application role may UPDATE ``default_mode``, ``default_model``
  and ``default_reasoning`` only (a tenant admin sets the defaults among the tenant's
  enabled options); tags, name and slug stay with the operator's package builder.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

APP_ROLE = "askspore_app"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
WORKSPACE_DEFAULTS = "default_mode, default_model, default_reasoning"

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("retention_days", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "retention_days BETWEEN 1 AND 30", name=op.f("ck_tenant_settings_retention_cap")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_settings_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenant_settings")),
    )
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute("ALTER TABLE tenant_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_settings FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON tenant_settings "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )
    op.execute(f"GRANT SELECT, INSERT ON tenant_settings TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (retention_days, updated_at) ON tenant_settings TO {APP_ROLE}")

    op.execute(f"GRANT INSERT ON users TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (role) ON users TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE ({WORKSPACE_DEFAULTS}) ON workspaces TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE ({WORKSPACE_DEFAULTS}) ON workspaces FROM {APP_ROLE}")
    op.execute(f"REVOKE UPDATE (role) ON users FROM {APP_ROLE}")
    op.execute(f"REVOKE INSERT ON users FROM {APP_ROLE}")
    op.drop_table("tenant_settings")
