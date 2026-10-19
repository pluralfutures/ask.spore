"""P1a-02: pending sign-in links and the pre-authentication lookup role.

Before a user is authenticated there is no tenant to scope a transaction to, yet a
sign-in request names only an email address, and the post-click POST carries only a
link token and the browser-binding cookie. Rather than weakening the tenant
policies, this revision adds a separate, narrow role:

- ``askspore_auth``: NOLOGIN, no BYPASSRLS. ``askspore_app`` may ``SET ROLE`` to it
  but does not inherit its privileges (``INHERIT FALSE``), so ordinary requests never
  have them. It reads only the columns needed to decide whether a link may be sent
  (tenant and user status, the sign-in-links entitlement, the email) through
  ``FOR SELECT TO askspore_auth`` policies, and reads and writes ``sign_in_links``.
  It cannot read conversations, messages, names or anything else.
- ``sign_in_links``: one row per link request for a known user: the SHA-256 of the
  browser-binding secret (the cookie set on the requesting browser), expiry (at most
  15 minutes), and on the first POST the SHA-256 of the submitted link token and the
  time it was consumed. Tenant-scoped: ``tenant_id``, forced RLS and a
  ``tenant_id``-first index from this first migration.
- ``askspore_app`` gets UPDATE on ``users`` (``status``, ``last_login_at``,
  ``last_login_method`` only), to record a sign-in under the user's tenant scope.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

APP_ROLE = "askspore_app"
AUTH_ROLE = "askspore_auth"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
# Column-level reads for the lookup role; nothing else on these tables.
AUTH_READS = {
    "tenants": "id, status",
    "users": "id, tenant_id, email, status",
    "tenant_entitlements": "tenant_id, sign_in_links_enabled",
}

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sign_in_links",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("binding_hash", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '15 minutes'",
            name=op.f("ck_sign_in_links_expiry_cap"),
        ),
        sa.CheckConstraint(
            "binding_hash ~ '^[0-9a-f]{64}$' AND token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_sign_in_links_hashes_hex"),
        ),
        sa.CheckConstraint(
            "(consumed_at IS NULL) = (token_hash IS NULL)",
            name=op.f("ck_sign_in_links_consumed_with_token"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_sign_in_links_tenant_id_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_sign_in_links_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sign_in_links")),
        sa.UniqueConstraint("binding_hash", name=op.f("uq_sign_in_links_binding_hash")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sign_in_links_token_hash")),
    )
    op.create_index(
        op.f("ix_sign_in_links_tenant_id_user_id_created_at"),
        "sign_in_links",
        ["tenant_id", "user_id", "created_at"],
        unique=False,
    )
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute("ALTER TABLE sign_in_links ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sign_in_links FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON sign_in_links "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{AUTH_ROLE}') THEN
                CREATE ROLE {AUTH_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            ELSIF EXISTS (
                SELECT FROM pg_roles
                WHERE rolname = '{AUTH_ROLE}' AND (rolsuper OR rolbypassrls OR rolcanlogin)
            ) THEN
                RAISE EXCEPTION '{AUTH_ROLE} must be NOLOGIN and must not bypass RLS';
            END IF;
        END
        $$
        """
    )
    # SET only: the app role can switch to it in a transaction but never inherits it.
    op.execute(f"GRANT {AUTH_ROLE} TO {APP_ROLE} WITH INHERIT FALSE, SET TRUE")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {AUTH_ROLE}")
    for table, columns in AUTH_READS.items():
        op.execute(f"GRANT SELECT ({columns}) ON {table} TO {AUTH_ROLE}")
        op.execute(f"CREATE POLICY auth_lookup ON {table} FOR SELECT TO {AUTH_ROLE} USING (true)")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON sign_in_links TO {AUTH_ROLE}")
    op.execute(
        f"CREATE POLICY auth_lookup ON sign_in_links TO {AUTH_ROLE} USING (true) WITH CHECK (true)"
    )

    op.execute(f"GRANT UPDATE (status, last_login_at, last_login_method) ON users TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE (status, last_login_at, last_login_method) ON users FROM {APP_ROLE}")
    for table, columns in AUTH_READS.items():
        op.execute(f"DROP POLICY auth_lookup ON {table}")
        op.execute(f"REVOKE SELECT ({columns}) ON {table} FROM {AUTH_ROLE}")
    op.drop_index(op.f("ix_sign_in_links_tenant_id_user_id_created_at"), table_name="sign_in_links")
    op.drop_table("sign_in_links")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {AUTH_ROLE}")
    # The role is cluster-wide (like askspore_app) and is kept; only its membership goes.
    op.execute(f"REVOKE {AUTH_ROLE} FROM {APP_ROLE}")
