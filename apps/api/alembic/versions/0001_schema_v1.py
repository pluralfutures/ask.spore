"""P0-05: schema v1.

Tables, plus the isolation controls that must exist from the first migration
(CLAUDE.md):

- the non-owner application role ``askspore_app`` and its grants;
- row-level security, enabled and forced, on every tenant-scoped table, keyed on
  ``current_setting('app.tenant_id')``; with no tenant set, policies match nothing;
- a ``tenant_id``-first index on every tenant-scoped table (the unique
  ``(tenant_id, id)`` constraints, which also back the composite foreign keys);
- ``audit_events`` append-only: SELECT/INSERT grants only, and a trigger that
  rejects UPDATE, DELETE and TRUNCATE for every role;
- seeds: the ``internal`` tenant and the users listed in PHASE0_INTERNAL_USERS.

Revision ID: 0001
Revises:
Create Date: 2026-10-17 16:12:02.184955
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = "askspore_app"
INTERNAL_TENANT_ID = "00000000-0000-4000-8000-000000000001"
# Every table with a tenant_id column. tenants itself is scoped on id.
TENANT_TABLES = ("users", "conversations", "messages", "citations", "feedback", "audit_events")
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("tag", sa.Text(), nullable=False),
        sa.Column("ragflow_dataset_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("tag", name=op.f("pk_datasets")),
        sa.UniqueConstraint("ragflow_dataset_id", name=op.f("uq_datasets_ragflow_dataset_id")),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("licence_basis", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'registered'"), nullable=False),
        sa.Column("file_sha256", sa.Text(), nullable=True),
        sa.Column(
            "ragflow_document_ids",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "file_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_sources_file_sha256_hex")
        ),
        sa.CheckConstraint(
            "status IN ('registered', 'ingesting', 'ingested', 'failed', 'withdrawn')",
            name=op.f("ck_sources_status_valid"),
        ),
        sa.CheckConstraint(
            "type IN ('pdf', 'docx', 'pptx', 'html', 'markdown')",
            name=op.f("ck_sources_type_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
    )
    op.create_table(
        "tenants",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("event", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_audit_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_audit_events_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_audit_events_tenant_id_created_at"),
        "audit_events",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_users_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("tenant_id", "email", name=op.f("uq_users_tenant_id_email")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_users_tenant_id_id")),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now() + interval '30 days'"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '30 days'",
            name=op.f("ck_conversations_retention_cap"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_conversations_tenant_id_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_conversations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_conversations_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_conversations_tenant_id_expires_at"),
        "conversations",
        ["tenant_id", "expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversations_tenant_id_user_id_updated_at"),
        "conversations",
        ["tenant_id", "user_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), server_default=sa.text("'corpus_only'"), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("mode IN ('corpus_only')", name=op.f("ck_messages_mode_valid")),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_messages_role_valid")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name=op.f("fk_messages_tenant_id_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_messages_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_messages_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_messages_tenant_id_conversation_id_created_at"),
        "messages",
        ["tenant_id", "conversation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "citations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("marker", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("ragflow_chunk_id", sa.Text(), nullable=False),
        sa.Column("page_or_slide", sa.Integer(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.CheckConstraint("marker > 0", name=op.f("ck_citations_marker_positive")),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name=op.f("fk_citations_source_id_sources")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "message_id"],
            ["messages.tenant_id", "messages.id"],
            name=op.f("fk_citations_tenant_id_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_citations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_citations")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_citations_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "message_id",
            "marker",
            name=op.f("uq_citations_tenant_id_message_id_marker"),
        ),
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rating IN ('up', 'down')", name=op.f("ck_feedback_rating_valid")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "message_id"],
            ["messages.tenant_id", "messages.id"],
            name=op.f("fk_feedback_tenant_id_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_feedback_tenant_id_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_feedback_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_feedback_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "message_id",
            "user_id",
            name=op.f("uq_feedback_tenant_id_message_id_user_id"),
        ),
    )
    _create_app_role()
    _enable_row_level_security()
    _make_audit_append_only()
    _seed()


def downgrade() -> None:
    # The askspore_app role is cluster-wide and may serve other databases; it is kept.
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.drop_table("feedback")
    op.drop_table("citations")
    op.drop_index(op.f("ix_messages_tenant_id_conversation_id_created_at"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_conversations_tenant_id_user_id_updated_at"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_tenant_id_expires_at"), table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("users")
    op.drop_index(op.f("ix_audit_events_tenant_id_created_at"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("tenants")
    op.drop_table("sources")
    op.drop_table("datasets")
    op.execute("DROP FUNCTION IF EXISTS audit_events_reject_change()")


def _create_app_role() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            ELSIF EXISTS (
                SELECT FROM pg_roles
                WHERE rolname = '{APP_ROLE}' AND (rolsuper OR rolbypassrls)
            ) THEN
                RAISE EXCEPTION '{APP_ROLE} must not be superuser or bypass RLS';
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    # Phase 0 has no user or tenant management through the API.
    op.execute(f"GRANT SELECT ON tenants, users TO {APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON conversations, messages, citations, feedback "
        f"TO {APP_ROLE}"
    )
    op.execute(f"GRANT SELECT, INSERT ON audit_events TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON sources, datasets TO {APP_ROLE}")


def _enable_row_level_security() -> None:
    policies = {table: f"tenant_id = {CURRENT_TENANT}" for table in TENANT_TABLES}
    policies["tenants"] = f"id = {CURRENT_TENANT}"
    for table, predicate in policies.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def _make_audit_append_only() -> None:
    op.execute(
        """
        CREATE FUNCTION audit_events_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_reject_change()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_reject_change()"
    )


def _parse_seed_users(raw: str) -> list[tuple[str, str]]:
    """PHASE0_INTERNAL_USERS: comma-separated ``email:Display Name`` pairs."""
    users = []
    for item in filter(None, (part.strip() for part in raw.split(","))):
        email, _, name = item.partition(":")
        email = email.strip().lower()
        if "@" not in email:
            raise ValueError("PHASE0_INTERNAL_USERS: each entry must be email:Display Name")
        users.append((email, name.strip() or email.split("@")[0]))
    return users


def _seed() -> None:
    # Policies are forced, so the owner must scope itself to the tenant it seeds.
    op.execute(f"SELECT set_config('app.tenant_id', '{INTERNAL_TENANT_ID}', true)")
    op.get_bind().execute(
        sa.text("INSERT INTO tenants (id, slug, name) VALUES (:id, 'internal', 'Internal')"),
        {"id": INTERNAL_TENANT_ID},
    )
    for email, name in _parse_seed_users(os.environ.get("PHASE0_INTERNAL_USERS", "")):
        op.get_bind().execute(
            sa.text(
                "INSERT INTO users (tenant_id, email, display_name) VALUES (:tenant, :email, :name)"
            ),
            {"tenant": INTERNAL_TENANT_ID, "email": email, "name": name},
        )
