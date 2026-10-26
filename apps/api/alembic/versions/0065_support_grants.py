"""P2A-08: time-boxed support access (architecture §7.4; consent notice v1 §1 and §7).

- ``support_grants``: a tenant admin's grant of read access to one scope of their
  tenant, ``settings`` or one ``conversation`` (by ID), for 15 minutes to 4 hours, with a
  note. Tenant-scoped from this first migration: ``tenant_id``, RLS enabled and forced
  with the ``tenant_isolation`` policy, and a ``tenant_id``-first index. The application
  role inserts grants and may update only ``revoked_at``; a trigger refuses
  un-revoking, reopening a closed grant and any other change. The row names no user:
  the audit events name the admin who granted or revoked it
  (``tenant_admin.support_granted``, ``tenant_admin.support_revoked``), so removing a
  user (revision 0051) leaves the grant records as termination would.
- A new NOLOGIN role **``askspore_support``**, which the application role may assume for
  one transaction (``SET LOCAL ROLE``) but does not inherit, as for the other narrow
  roles. The operator's support routes take it with ``app.tenant_id`` set to the
  grant's tenant (``app.support.access``). It reads the tenant's grants, and the
  columns a user sees of a conversation (``conversations``, ``messages``,
  ``citations``, the cited ``sources``' provenance) or of the tenant's settings
  (``tenant_settings``, ``workspaces``, ``workspace_prompts``), and inserts its
  ``operator.support_viewed`` audit event. It writes nothing else.
- On each of those tenant tables a **restrictive** policy ``support_grant`` for the role
  only: a conversation, its messages and citations are visible only while an open grant
  (not revoked, not closed, ``expires_at`` in the future) names that conversation, and
  the settings tables only while an open ``settings`` grant exists. The tables'
  ``tenant_isolation`` policies still apply, so the database enforces the grant's
  tenant, scope and expiry on every read, under the application's own check.
- The retention role (revision 0040) may read a grant's state columns and set
  ``closed_at``, and insert the ``support.grant_expired`` audit event: the daily purge
  closes expired grants (``app.tenancy.purge``).

Revision ID: 0065
Revises: 0060
Create Date: 2026-10-25 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

APP_ROLE = "askspore_app"
SUPPORT_ROLE = "askspore_support"
RETENTION_ROLE = "askspore_retention"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
OPEN_GRANT = "g.revoked_at IS NULL AND g.closed_at IS NULL AND g.expires_at > now()"

# What the support role may read, per table: what a user sees, nothing more.
SUPPORT_READABLE = {
    "support_grants": (
        "id, tenant_id, scope, conversation_id, duration_minutes, note, created_at, "
        "expires_at, revoked_at, closed_at"
    ),
    "conversations": (
        "id, tenant_id, workspace_id, title, created_at, updated_at, expires_at, mode, model"
    ),
    "messages": (
        "id, tenant_id, conversation_id, role, content, mode, created_at, outcome, "
        "truncated, partial"
    ),
    "citations": (
        "id, tenant_id, message_id, marker, source_id, page_or_slide, excerpt, "
        "superseded_at, withdrawn_at"
    ),
    "sources": "id, title, publisher, published_on, canonical_url, type",
    "tenant_settings": "tenant_id, retention_days",
    "workspaces": "id, tenant_id, name, slug, default_mode, default_model, default_reasoning",
    "workspace_prompts": "id, tenant_id, workspace_id, version, text, created_at",
}
CONVERSATION_POLICIES = {
    "conversations": (
        f"EXISTS (SELECT 1 FROM support_grants g WHERE g.tenant_id = conversations.tenant_id "
        f"AND g.scope = 'conversation' AND g.conversation_id = conversations.id AND {OPEN_GRANT})"
    ),
    "messages": (
        f"EXISTS (SELECT 1 FROM support_grants g WHERE g.tenant_id = messages.tenant_id "
        f"AND g.scope = 'conversation' AND g.conversation_id = messages.conversation_id "
        f"AND {OPEN_GRANT})"
    ),
    "citations": (
        "EXISTS (SELECT 1 FROM messages m JOIN support_grants g "
        "ON g.tenant_id = m.tenant_id AND g.conversation_id = m.conversation_id "
        f"WHERE m.id = citations.message_id AND m.tenant_id = citations.tenant_id "
        f"AND g.scope = 'conversation' AND {OPEN_GRANT})"
    ),
}
SETTINGS_TABLES = ("tenant_settings", "workspaces", "workspace_prompts")

revision: str = "0065"
down_revision: str | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _settings_policy(table: str) -> str:
    return (
        f"EXISTS (SELECT 1 FROM support_grants g WHERE g.tenant_id = {table}.tenant_id "
        f"AND g.scope = 'settings' AND {OPEN_GRANT})"
    )


def upgrade() -> None:
    op.create_table(
        "support_grants",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope IN ('settings', 'conversation')", name=op.f("ck_support_grants_scope_valid")
        ),
        sa.CheckConstraint(
            "(scope = 'conversation') = (conversation_id IS NOT NULL)",
            name=op.f("ck_support_grants_conversation_scope"),
        ),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 15 AND 240", name=op.f("ck_support_grants_duration_range")
        ),
        sa.CheckConstraint(
            "expires_at = created_at + make_interval(mins => duration_minutes)",
            name=op.f("ck_support_grants_expiry_from_duration"),
        ),
        sa.CheckConstraint(
            "length(btrim(note)) BETWEEN 1 AND 500", name=op.f("ck_support_grants_note_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_support_grants_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_grants")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_support_grants_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_support_grants_tenant_id_created_at"),
        "support_grants",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        op.f("ix_support_grants_tenant_id_conversation_id"),
        "support_grants",
        ["tenant_id", "conversation_id"],
    )
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute("ALTER TABLE support_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE support_grants FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON support_grants USING ({predicate}) "
        f"WITH CHECK ({predicate})"
    )
    # A revoked grant stays revoked, a closed one closed; nothing else changes.
    op.execute(
        """
        CREATE FUNCTION support_grants_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.id, NEW.tenant_id, NEW.scope, NEW.conversation_id, NEW.duration_minutes,
                NEW.note, NEW.created_at, NEW.expires_at)
               IS DISTINCT FROM
               (OLD.id, OLD.tenant_id, OLD.scope, OLD.conversation_id, OLD.duration_minutes,
                OLD.note, OLD.created_at, OLD.expires_at) THEN
                RAISE EXCEPTION 'support grant fields are immutable';
            END IF;
            IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
                RAISE EXCEPTION 'a revoked support grant stays revoked';
            END IF;
            IF OLD.closed_at IS NOT NULL AND NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN
                RAISE EXCEPTION 'a closed support grant stays closed';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER support_grants_guard BEFORE UPDATE ON support_grants "
        "FOR EACH ROW EXECUTE FUNCTION support_grants_guard()"
    )
    op.execute(f"GRANT SELECT, INSERT ON support_grants TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (revoked_at) ON support_grants TO {APP_ROLE}")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{SUPPORT_ROLE}') THEN
                CREATE ROLE {SUPPORT_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB
                    NOCREATEROLE;
            ELSIF EXISTS (
                SELECT FROM pg_roles
                WHERE rolname = '{SUPPORT_ROLE}' AND (rolsuper OR rolbypassrls OR rolcanlogin)
            ) THEN
                RAISE EXCEPTION '{SUPPORT_ROLE} must be NOLOGIN and must not bypass RLS';
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT {SUPPORT_ROLE} TO {APP_ROLE} WITH INHERIT FALSE, SET TRUE")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {SUPPORT_ROLE}")
    for table, columns in SUPPORT_READABLE.items():
        op.execute(f"GRANT SELECT ({columns}) ON {table} TO {SUPPORT_ROLE}")
    # Its own audit event, in the transaction that reads (RETURNING needs the columns).
    op.execute(
        f"GRANT SELECT (id, tenant_id, created_at), INSERT ON audit_events TO {SUPPORT_ROLE}"
    )
    for table, condition in CONVERSATION_POLICIES.items():
        op.execute(
            f"CREATE POLICY support_grant ON {table} AS RESTRICTIVE FOR SELECT "
            f"TO {SUPPORT_ROLE} USING ({condition})"
        )
    for table in SETTINGS_TABLES:
        op.execute(
            f"CREATE POLICY support_grant ON {table} AS RESTRICTIVE FOR SELECT "
            f"TO {SUPPORT_ROLE} USING ({_settings_policy(table)})"
        )

    op.execute(
        f"GRANT SELECT (id, tenant_id, expires_at, revoked_at, closed_at) ON support_grants "
        f"TO {RETENTION_ROLE}"
    )
    op.execute(f"GRANT UPDATE (closed_at) ON support_grants TO {RETENTION_ROLE}")
    op.execute(
        f"GRANT SELECT (id, tenant_id, created_at), INSERT ON audit_events TO {RETENTION_ROLE}"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT (id, tenant_id, created_at), INSERT ON audit_events FROM {RETENTION_ROLE}"
    )
    for table in (*CONVERSATION_POLICIES, *SETTINGS_TABLES):
        op.execute(f"DROP POLICY support_grant ON {table}")
    op.execute(
        f"REVOKE SELECT (id, tenant_id, created_at), INSERT ON audit_events FROM {SUPPORT_ROLE}"
    )
    for table, columns in SUPPORT_READABLE.items():
        if table != "support_grants":
            op.execute(f"REVOKE SELECT ({columns}) ON {table} FROM {SUPPORT_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {SUPPORT_ROLE}")
    # The role is cluster-wide (like askspore_app) and is kept; only its membership goes.
    op.execute(f"REVOKE {SUPPORT_ROLE} FROM {APP_ROLE}")
    op.drop_table("support_grants")
    op.execute("DROP FUNCTION support_grants_guard()")
