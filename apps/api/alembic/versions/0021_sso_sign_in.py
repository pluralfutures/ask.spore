"""P1b-07: sign-in through a tenant's Authentik source (Entra ID, Google, OIDC, SAML).

- ``sso_attempts``: one row per SSO sign-in started from the login page, bound to the
  browser that started it like a sign-in link (P1a-02): the SHA-256 of a random binding
  secret held in that browser's cookie, the tenant the address's domain resolved to,
  the Authentik source's slug, expiry (at most 10 minutes) and when the IdP's answer
  consumed it. The callback finds the tenant here, never in the IdP's answer.
  Tenant-scoped: ``tenant_id``, forced RLS and a ``tenant_id``-first index from this
  first migration. Only ``askspore_auth`` (pre-authentication, revision 0005) reads and
  writes it; the application role has no privileges on it.
- ``users.last_login_method`` admits ``sso``.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-21 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

AUTH_ROLE = "askspore_auth"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sso_attempts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("binding_hash", sa.Text(), nullable=False),
        sa.Column("source_slug", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '10 minutes'",
            name=op.f("ck_sso_attempts_expiry_cap"),
        ),
        sa.CheckConstraint(
            "binding_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_sso_attempts_binding_hash_hex")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_sso_attempts_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sso_attempts")),
        sa.UniqueConstraint("binding_hash", name=op.f("uq_sso_attempts_binding_hash")),
    )
    op.create_index(
        op.f("ix_sso_attempts_tenant_id_created_at"),
        "sso_attempts",
        ["tenant_id", "created_at"],
        unique=False,
    )
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute("ALTER TABLE sso_attempts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sso_attempts FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON sso_attempts "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON sso_attempts TO {AUTH_ROLE}")
    op.execute(
        f"CREATE POLICY auth_lookup ON sso_attempts TO {AUTH_ROLE} USING (true) WITH CHECK (true)"
    )

    op.drop_constraint(op.f("ck_users_login_method_valid"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_login_method_valid"),
        "users",
        "last_login_method IN ('sign_in_link', 'sso')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE users SET last_login_method = 'sign_in_link' WHERE last_login_method = 'sso'"
    )
    op.drop_constraint(op.f("ck_users_login_method_valid"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_login_method_valid"), "users", "last_login_method IN ('sign_in_link')"
    )
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON sso_attempts FROM {AUTH_ROLE}")
    op.drop_index(op.f("ix_sso_attempts_tenant_id_created_at"), table_name="sso_attempts")
    op.drop_table("sso_attempts")
