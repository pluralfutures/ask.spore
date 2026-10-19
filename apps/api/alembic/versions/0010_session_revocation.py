"""P1a-02: sign-out revokes the session (owner decision, Group A open question).

- ``revoked_sessions(tenant_id, token_sha256, user_id, revoked_at, expires_at)``: the
  SHA-256 of every access token whose holder signed out. The API validates Authentik's
  access tokens locally (JWKS), so clearing the cookie alone leaves a copied token
  usable until it expires; authentication refuses a token listed here. Only the hash
  is stored. ``expires_at`` is the token's own expiry: after it the row is inert (the
  token is refused anyway) and may be purged (Phase 1b retention jobs).
  Tenant-scoped: forced RLS, primary key ``(tenant_id, token_sha256)``. The
  application role may read and insert, not update or delete, so a revocation cannot
  be undone through the API.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-19 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

APP_ROLE = "askspore_app"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "revoked_sessions",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("token_sha256", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "token_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_revoked_sessions_token_sha256_hex")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_revoked_sessions_tenant_id_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "token_sha256", name=op.f("pk_revoked_sessions")),
    )
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute("ALTER TABLE revoked_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE revoked_sessions FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON revoked_sessions "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )
    op.execute(f"GRANT SELECT, INSERT ON revoked_sessions TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("revoked_sessions")
