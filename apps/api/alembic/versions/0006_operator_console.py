"""P1a-03: operator console, minimum.

- ``operators``: which users of the internal (platform) tenant are platform operators.
  Keyed ``(tenant_id, user_id)`` onto ``users``, with ``tenant_id`` pinned to the
  internal tenant; forced RLS and a ``tenant_id``-first key like every table with a
  ``tenant_id``. Granted by the ``ask-spore operators grant`` command as the owner,
  never through the API.
- ``askspore_operator``: the role operator routes run as (``SET LOCAL ROLE``), outside
  tenant RLS. NOLOGIN, no BYPASSRLS; ``askspore_app`` may assume it but does not
  inherit it. Its policies (``TO askspore_operator``) see every tenant, but it holds
  privileges only on what the console manages: tenants, users (create invited users),
  entitlements, operator notices and audit events (read and append). It has none on
  conversations, messages, citations, feedback, sign-in links or the corpus, so no
  operator code path can read a tenant's chat content.
- ``tenant_entitlements`` gains the client's acceptance of external models (revised
  P1a-03, Oct 19, 2026): ``external_acceptance_reference`` (the client DPA document)
  and ``external_acceptance_date``. A check constraint refuses
  ``external_models_enabled`` without both and without a spend cap, whoever writes.
- ``operator_notices``: notices for the operator console (fed by P1a-07 and P1a-10).
  Tenant-scoped (forced RLS, ``tenant_id``-first index); the operator reads them.
  The application role gets no privileges here yet: the items that write notices
  grant INSERT in their own migrations.
- ``askspore_auth`` (revision 0005) may read ``operators``, to tell an operator from
  any other signed-in user before switching to ``askspore_operator``.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19 12:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = "askspore_app"
AUTH_ROLE = "askspore_auth"
OPERATOR_ROLE = "askspore_operator"
INTERNAL_TENANT_ID = "00000000-0000-4000-8000-000000000001"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
# What the operator role may do, table by table. Nothing else.
OPERATOR_GRANTS = {
    "tenants": "SELECT, INSERT, UPDATE",
    "users": "SELECT, INSERT",
    "tenant_entitlements": "SELECT, INSERT, UPDATE",
    "operator_notices": "SELECT",
    "audit_events": "SELECT, INSERT",
    "operators": "SELECT",
}

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_isolation(table: str) -> None:
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})"
    )


def upgrade() -> None:
    op.add_column(
        "tenant_entitlements", sa.Column("external_acceptance_reference", sa.Text(), nullable=True)
    )
    op.add_column(
        "tenant_entitlements", sa.Column("external_acceptance_date", sa.Date(), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_tenant_entitlements_external_needs_acceptance"),
        "tenant_entitlements",
        "NOT external_models_enabled OR (length(btrim(external_acceptance_reference)) > 0 "
        "AND external_acceptance_date IS NOT NULL AND external_spend_cap_cents IS NOT NULL)",
    )

    op.create_table(
        "operators",
        sa.Column(
            "tenant_id",
            sa.UUID(),
            server_default=sa.text(f"'{INTERNAL_TENANT_ID}'::uuid"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"tenant_id = '{INTERNAL_TENANT_ID}'::uuid", name=op.f("ck_operators_internal_tenant")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_operators_tenant_id_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_operators_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", name=op.f("pk_operators")),
    )
    _tenant_isolation("operators")

    op.create_table(
        "operator_notices",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind ~ '^[a-z][a-z0-9_]*(\\.[a-z0-9_]+)*$'",
            name=op.f("ck_operator_notices_kind_format"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_operator_notices_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operator_notices")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_operator_notices_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_operator_notices_tenant_id_created_at"),
        "operator_notices",
        ["tenant_id", "created_at"],
        unique=False,
    )
    _tenant_isolation("operator_notices")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{OPERATOR_ROLE}') THEN
                CREATE ROLE {OPERATOR_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            ELSIF EXISTS (
                SELECT FROM pg_roles
                WHERE rolname = '{OPERATOR_ROLE}' AND (rolsuper OR rolbypassrls OR rolcanlogin)
            ) THEN
                RAISE EXCEPTION '{OPERATOR_ROLE} must be NOLOGIN and must not bypass RLS';
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT {OPERATOR_ROLE} TO {APP_ROLE} WITH INHERIT FALSE, SET TRUE")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {OPERATOR_ROLE}")
    for table, privileges in OPERATOR_GRANTS.items():
        op.execute(f"GRANT {privileges} ON {table} TO {OPERATOR_ROLE}")
        op.execute(
            f"CREATE POLICY operator_console ON {table} TO {OPERATOR_ROLE} "
            f"USING (true) WITH CHECK (true)"
        )

    op.execute(f"GRANT SELECT (tenant_id, user_id) ON operators TO {AUTH_ROLE}")
    op.execute(f"CREATE POLICY auth_lookup ON operators FOR SELECT TO {AUTH_ROLE} USING (true)")


def downgrade() -> None:
    op.execute("DROP POLICY auth_lookup ON operators")
    op.execute(f"REVOKE SELECT (tenant_id, user_id) ON operators FROM {AUTH_ROLE}")
    for table, privileges in OPERATOR_GRANTS.items():
        op.execute(f"DROP POLICY operator_console ON {table}")
        op.execute(f"REVOKE {privileges} ON {table} FROM {OPERATOR_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {OPERATOR_ROLE}")
    # The role is cluster-wide (like askspore_app) and is kept; only its membership goes.
    op.execute(f"REVOKE {OPERATOR_ROLE} FROM {APP_ROLE}")
    op.drop_index(op.f("ix_operator_notices_tenant_id_created_at"), table_name="operator_notices")
    op.drop_table("operator_notices")
    op.drop_table("operators")
    op.drop_constraint(
        op.f("ck_tenant_entitlements_external_needs_acceptance"),
        "tenant_entitlements",
        type_="check",
    )
    op.drop_column("tenant_entitlements", "external_acceptance_date")
    op.drop_column("tenant_entitlements", "external_acceptance_reference")
