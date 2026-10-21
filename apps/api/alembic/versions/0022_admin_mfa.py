"""P1b-08: second factor for tenant admins on sign-in links.

Authentik challenges members of the ``ask-spore-tenant-admins`` group for a TOTP code
in the sign-in-link flow (an authenticator validation stage bound to that group). The
API runs the flow and relays the challenge to the browser that holds the link's
binding; between the link POST and the code POST the challenge waits here.

- ``mfa_challenges``: one row per pending challenge: the tenant and user the link was
  for, the SHA-256 of a new binding secret held in that browser's cookie (Authentik's
  pending session travels in the browser's cookie too, never in our database), expiry
  (at most 5 minutes), the number of codes tried (at most 5) and when it completed.
  Tenant-scoped: ``tenant_id``, forced RLS and a ``tenant_id``-first index from this
  first migration; composite foreign key onto ``users``. Only ``askspore_auth``
  (pre-authentication, revision 0005) reads and writes it.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-21 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

AUTH_ROLE = "askspore_auth"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
MAX_ATTEMPTS = 5

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mfa_challenges",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("binding_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '5 minutes'",
            name=op.f("ck_mfa_challenges_expiry_cap"),
        ),
        sa.CheckConstraint(
            f"attempts BETWEEN 0 AND {MAX_ATTEMPTS}", name=op.f("ck_mfa_challenges_attempts_cap")
        ),
        sa.CheckConstraint(
            "binding_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_mfa_challenges_binding_hash_hex")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_mfa_challenges_tenant_id_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_mfa_challenges_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mfa_challenges")),
        sa.UniqueConstraint("binding_hash", name=op.f("uq_mfa_challenges_binding_hash")),
    )
    op.create_index(
        op.f("ix_mfa_challenges_tenant_id_user_id_created_at"),
        "mfa_challenges",
        ["tenant_id", "user_id", "created_at"],
        unique=False,
    )
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute("ALTER TABLE mfa_challenges ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mfa_challenges FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON mfa_challenges "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON mfa_challenges TO {AUTH_ROLE}")
    op.execute(
        f"CREATE POLICY auth_lookup ON mfa_challenges TO {AUTH_ROLE} USING (true) WITH CHECK (true)"
    )


def downgrade() -> None:
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON mfa_challenges FROM {AUTH_ROLE}")
    op.drop_index(
        op.f("ix_mfa_challenges_tenant_id_user_id_created_at"), table_name="mfa_challenges"
    )
    op.drop_table("mfa_challenges")
