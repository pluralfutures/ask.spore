"""P1b-06: per-tenant login policy and tenant discovery by email domain.

- ``tenant_login_policy(tenant_id, sign_in_links_enabled, sso_source_kind,
  sso_source_slug, sso_source_config, jit_provisioning_enabled, admin_mfa_required,
  updated_at)``: how a tenant's users sign in (architecture §4.3, §7.4). One row per
  tenant, keyed by ``tenant_id`` (the ``tenant_id``-first index); forced RLS with the
  ``tenant_isolation`` policy from this first migration.
  - ``sign_in_links_enabled`` moves here from ``tenant_entitlements`` (values copied,
    the old column dropped). On by default (owner decision, Oct 17, 2026).
  - ``sso_source_kind``: ``none``, ``entra``, ``google``, ``oidc`` or ``saml``; with
    ``sso_source_slug``, the Authentik source's slug (P1b-07), set exactly when a kind
    is. ``sso_source_config`` holds non-secret fields only (client ID, Entra tenant ID,
    issuer, SAML entity ID and certificate fingerprint); client secrets and SAML keys
    stay in Authentik.
  - ``jit_provisioning_enabled`` (off by default) and ``admin_mfa_required`` (on).
- A trigger gives every new tenant its row with the defaults, so a tenant never lacks
  a policy and sign-in code can require the row (fail closed).
- ``askspore_operator`` (the console, P1a-03) may read, insert and update the policy;
  ``askspore_auth`` (pre-authentication, P1a-02) reads the columns discovery and link
  sending need; ``askspore_app`` may read its own tenant's row (link completion, the
  tenant admin's read-only view), never write it.

Numbered 0020 on 0012 while Group A1 added 0013 to 0015 in parallel; re-parented onto 0015 at the
integration step of Oct 22, 2026.

Revision ID: 0020
Revises: 0015
Create Date: 2026-10-21 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = "askspore_app"
AUTH_ROLE = "askspore_auth"
OPERATOR_ROLE = "askspore_operator"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
SSO_KINDS = "'none', 'entra', 'google', 'oidc', 'saml'"
AUTH_COLUMNS = (
    "tenant_id, sign_in_links_enabled, sso_source_kind, sso_source_slug, "
    "jit_provisioning_enabled, admin_mfa_required"
)

revision: str = "0020"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_login_policy",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "sign_in_links_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("sso_source_kind", sa.Text(), server_default=sa.text("'none'"), nullable=False),
        sa.Column("sso_source_slug", sa.Text(), nullable=True),
        sa.Column(
            "sso_source_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "jit_provisioning_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "admin_mfa_required", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"sso_source_kind IN ({SSO_KINDS})", name=op.f("ck_tenant_login_policy_sso_kind_valid")
        ),
        sa.CheckConstraint(
            "(sso_source_kind = 'none') = (sso_source_slug IS NULL)",
            name=op.f("ck_tenant_login_policy_sso_slug_with_kind"),
        ),
        sa.CheckConstraint(
            "sso_source_slug ~ '^[a-z0-9][a-z0-9-]{1,70}$'",
            name=op.f("ck_tenant_login_policy_sso_slug_format"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(sso_source_config) = 'object'",
            name=op.f("ck_tenant_login_policy_sso_config_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_login_policy_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenant_login_policy")),
        sa.UniqueConstraint("sso_source_slug", name=op.f("uq_tenant_login_policy_sso_source_slug")),
    )
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute("ALTER TABLE tenant_login_policy ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_login_policy FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON tenant_login_policy "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )

    # Every existing tenant keeps its sign-in-links switch; the rest are defaults.
    op.execute(
        "INSERT INTO tenant_login_policy (tenant_id, sign_in_links_enabled) "
        "SELECT t.id, coalesce(e.sign_in_links_enabled, true) "
        "FROM tenants t LEFT JOIN tenant_entitlements e ON e.tenant_id = t.id"
    )
    op.drop_column("tenant_entitlements", "sign_in_links_enabled")

    # A new tenant gets its policy row in the same statement (as whoever inserts it).
    op.execute(
        """
        CREATE FUNCTION tenant_login_policy_default() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
        BEGIN
            INSERT INTO tenant_login_policy (tenant_id) VALUES (NEW.id);
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER tenant_login_policy_default AFTER INSERT ON tenants "
        "FOR EACH ROW EXECUTE FUNCTION tenant_login_policy_default()"
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON tenant_login_policy TO {OPERATOR_ROLE}")
    op.execute(
        f"CREATE POLICY operator_console ON tenant_login_policy TO {OPERATOR_ROLE} "
        f"USING (true) WITH CHECK (true)"
    )
    op.execute(f"GRANT SELECT ({AUTH_COLUMNS}) ON tenant_login_policy TO {AUTH_ROLE}")
    op.execute(
        f"CREATE POLICY auth_lookup ON tenant_login_policy FOR SELECT TO {AUTH_ROLE} USING (true)"
    )
    # Discovery maps an email domain to a tenant before anyone is authenticated.
    op.execute(f"GRANT SELECT (verified_domains) ON tenants TO {AUTH_ROLE}")
    op.execute(f"GRANT SELECT ON tenant_login_policy TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ON tenant_login_policy FROM {APP_ROLE}")
    op.execute(f"REVOKE SELECT (verified_domains) ON tenants FROM {AUTH_ROLE}")
    op.execute("DROP TRIGGER tenant_login_policy_default ON tenants")
    op.execute("DROP FUNCTION tenant_login_policy_default()")
    op.add_column(
        "tenant_entitlements",
        sa.Column(
            "sign_in_links_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )
    op.execute(
        "UPDATE tenant_entitlements e SET sign_in_links_enabled = p.sign_in_links_enabled "
        "FROM tenant_login_policy p WHERE p.tenant_id = e.tenant_id"
    )
    # Revision 0005's column grant, which dropping the column removed.
    op.execute(
        f"GRANT SELECT (tenant_id, sign_in_links_enabled) ON tenant_entitlements TO {AUTH_ROLE}"
    )
    op.drop_table("tenant_login_policy")
