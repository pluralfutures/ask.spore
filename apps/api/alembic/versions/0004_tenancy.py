"""P1a-01: tenants, users and tenant entitlements.

Phase 0 created ``tenants`` and ``users`` (revision 0001), with row-level security
and ``tenant_id``-first indexes from the start. This revision gives them the
Phase 1a columns and adds ``tenant_entitlements``:

- ``tenants``: ``name`` becomes ``display_name``; ``verified_domains`` (lower-case
  email domains, used for tenant-name matching and, later, JIT provisioning) and
  ``status`` (``active`` or ``suspended``);
- ``users``: ``role`` (``user`` or ``tenant_admin``), ``status`` (``invited``,
  ``active``, ``deactivated``), ``last_login_at`` and ``last_login_method``;
- ``tenant_entitlements``: one row per tenant, keyed by ``tenant_id`` (so its
  primary key is the ``tenant_id``-first index), with row-level security enabled
  and forced from this first migration, like every tenant-scoped table.

The Phase 0 ``internal`` tenant stays a row (seeded by 0001) and gets its
entitlements row here: corpus-only answers on the Phase 0 model, no external
models, sign-in links on. Seeded users stay ``user`` / ``active``.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19 09:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = "askspore_app"
INTERNAL_TENANT_ID = "00000000-0000-4000-8000-000000000001"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
# Answer modes that exist in Phase 1a. Web search (Phase 2) joins with its own migration.
ANSWER_MODES = ("corpus_only", "general_knowledge")
# The Phase 0 model (config/models.toml [scaleway] chat_model), the internal tenant's only one.
INTERNAL_MODEL = "deepseek-v4.1-flash"

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("tenants", "name", new_column_name="display_name")
    op.add_column(
        "tenants",
        sa.Column(
            "verified_domains",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_tenants_status_valid"), "tenants", "status IN ('active', 'suspended')"
    )
    op.create_check_constraint(
        op.f("ck_tenants_slug_format"), "tenants", "slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'"
    )
    op.create_check_constraint(
        op.f("ck_tenants_domains_lowercase"),
        "tenants",
        "verified_domains = lower(verified_domains::text)::text[]",
    )

    op.add_column(
        "users", sa.Column("role", sa.Text(), server_default=sa.text("'user'"), nullable=False)
    )
    op.add_column(
        "users",
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
    )
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_method", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_role_valid"), "users", "role IN ('user', 'tenant_admin')"
    )
    op.create_check_constraint(
        op.f("ck_users_status_valid"), "users", "status IN ('invited', 'active', 'deactivated')"
    )
    op.create_check_constraint(
        op.f("ck_users_login_method_valid"), "users", "last_login_method IN ('sign_in_link')"
    )

    modes = ", ".join(f"'{mode}'" for mode in ANSWER_MODES)
    op.create_table(
        "tenant_entitlements",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "answer_modes",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{corpus_only}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "enabled_models",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "external_models_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("external_spend_cap_cents", sa.Integer(), nullable=True),
        sa.Column(
            "sign_in_links_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"answer_modes <@ ARRAY[{modes}]::text[] AND 'corpus_only' = ANY(answer_modes)",
            name=op.f("ck_tenant_entitlements_answer_modes_valid"),
        ),
        sa.CheckConstraint(
            "external_spend_cap_cents >= 0",
            name=op.f("ck_tenant_entitlements_spend_cap_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_entitlements_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenant_entitlements")),
    )
    op.execute(f"GRANT SELECT ON tenant_entitlements TO {APP_ROLE}")
    op.execute("ALTER TABLE tenant_entitlements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_entitlements FORCE ROW LEVEL SECURITY")
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute(
        f"CREATE POLICY tenant_isolation ON tenant_entitlements "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )

    # Policies are forced, so the owner scopes itself to the tenant it seeds.
    op.execute(f"SELECT set_config('app.tenant_id', '{INTERNAL_TENANT_ID}', true)")
    op.get_bind().execute(
        sa.text(
            "INSERT INTO tenant_entitlements (tenant_id, enabled_models) "
            "VALUES (:tenant, ARRAY[:model])"
        ),
        {"tenant": INTERNAL_TENANT_ID, "model": INTERNAL_MODEL},
    )


def downgrade() -> None:
    op.drop_table("tenant_entitlements")
    for name in ("login_method_valid", "status_valid", "role_valid"):
        op.drop_constraint(op.f(f"ck_users_{name}"), "users", type_="check")
    for column in ("last_login_method", "last_login_at", "status", "role"):
        op.drop_column("users", column)
    for name in ("domains_lowercase", "slug_format", "status_valid"):
        op.drop_constraint(op.f(f"ck_tenants_{name}"), "tenants", type_="check")
    op.drop_column("tenants", "status")
    op.drop_column("tenants", "verified_domains")
    op.alter_column("tenants", "display_name", new_column_name="name")
