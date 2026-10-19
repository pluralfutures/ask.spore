"""P1a-04: workspaces, workspace prompts, and the workspace, mode, model and reasoning
of every conversation.

- ``workspaces``: the unit a user chooses when starting a conversation (architecture
  §14.1). ``tag_ids`` are the tag keys of ``config/tags.toml`` (the ``datasets``
  primary key); the API resolves them to RAGFlow dataset IDs server-side, never from a
  request. Tags may repeat across a tenant's workspaces (a common corpus). Defaults
  for the start panel: mode, model and reasoning.
- ``workspace_prompts``: the tenant-authored additional-instructions block, one row
  per saved version; the active prompt is the highest version. Append-only for the
  application role (SELECT and INSERT only) and capped at 2,000 characters.
- Both tables are tenant-scoped from this first migration: ``tenant_id``, forced RLS
  with the ``tenant_isolation`` policy, ``tenant_id``-first unique indexes, and
  composite ``(tenant_id, …)`` foreign keys so no row can point at another tenant's.
- ``conversations`` gains ``workspace_id``, ``mode``, ``model`` and ``reasoning``,
  fixed at creation: the application role keeps UPDATE only on ``title``,
  ``updated_at`` and ``expires_at``. ``messages`` gains ``reasoning`` (assistant
  messages record model and reasoning) and its mode check admits
  ``general_knowledge`` (P1a-06).
- ``askspore_operator`` may read, create and re-tag workspaces (the package builder)
  but has no privileges on ``workspace_prompts``: tenant-authored text stays with the
  tenant; the operator learns of tenant-name matches through notices (P1a-07).

Backfill: the internal tenant gets the workspace ``research`` with the Phase 0 package
(every tag in ``config/tags.toml`` today); any other tenant that already has
conversations gets ``default`` with no tags, so it keeps retrieving nothing (findings
A5) until the operator assigns tags. Existing conversations move to their tenant's
workspace in ``corpus_only`` mode with reasoning off (as Phase 0 ran) and the model of
their last answer, or the workspace default.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = "askspore_app"
OPERATOR_ROLE = "askspore_operator"
INTERNAL_TENANT_ID = "00000000-0000-4000-8000-000000000001"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
MODES = "('corpus_only', 'general_knowledge')"
# config/tags.toml on Oct 19, 2026: the Phase 0 package of the internal tenant.
PHASE0_TAGS = ("sample-reports", "sample-analysis", "sample-web")
PHASE0_MODEL = "deepseek-v4.1-flash"
PROMPT_MAX_CHARS = 2000
# Tables whose forced RLS the owner lifts for the backfill, inside this transaction.
BACKFILL_TABLES = ("tenants", "tenant_entitlements", "conversations", "messages", "workspaces")
CONVERSATION_UPDATABLE = "title, updated_at, expires_at"

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_isolation(table: str) -> None:
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})"
    )


def _create_tables() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "tag_ids",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "default_mode", sa.Text(), server_default=sa.text("'corpus_only'"), nullable=False
        ),
        sa.Column("default_model", sa.Text(), nullable=False),
        sa.Column(
            "default_reasoning", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'", name=op.f("ck_workspaces_slug_format")
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 128", name=op.f("ck_workspaces_name_length")
        ),
        sa.CheckConstraint(f"default_mode IN {MODES}", name=op.f("ck_workspaces_mode_valid")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_workspaces_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_workspaces_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "slug", name=op.f("uq_workspaces_tenant_id_slug")),
    )
    _tenant_isolation("workspaces")

    op.create_table(
        "workspace_prompts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("author_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_workspace_prompts_version_positive")),
        sa.CheckConstraint(
            f"length(text) <= {PROMPT_MAX_CHARS}", name=op.f("ck_workspace_prompts_text_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_workspace_prompts_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workspace_id"],
            ["workspaces.tenant_id", "workspaces.id"],
            name=op.f("fk_workspace_prompts_tenant_id_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "author_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_workspace_prompts_tenant_id_author_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_prompts")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_workspace_prompts_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "version",
            name=op.f("uq_workspace_prompts_tenant_id_workspace_id_version"),
        ),
    )
    _tenant_isolation("workspace_prompts")


def _backfill() -> None:
    # Policies are forced on the owner too; lift them for this transaction only.
    for table in BACKFILL_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO workspaces (tenant_id, slug, name, tag_ids, default_model) "
            "VALUES (:tenant, 'research', 'Research', CAST(:tags AS text[]), :model)"
        ),
        {"tenant": INTERNAL_TENANT_ID, "tags": list(PHASE0_TAGS), "model": PHASE0_MODEL},
    )
    bind.execute(
        sa.text(
            "INSERT INTO workspaces (tenant_id, slug, name, default_model) "
            "SELECT t.id, 'default', 'Default', coalesce(e.enabled_models[1], :model) "
            "FROM tenants t LEFT JOIN tenant_entitlements e ON e.tenant_id = t.id "
            "WHERE t.id <> CAST(:tenant AS uuid) "
            "AND EXISTS (SELECT 1 FROM conversations c WHERE c.tenant_id = t.id)"
        ),
        {"tenant": INTERNAL_TENANT_ID, "model": PHASE0_MODEL},
    )
    bind.execute(
        sa.text(
            "UPDATE conversations c SET workspace_id = w.id, mode = 'corpus_only', "
            "reasoning = false, model = coalesce("
            "  (SELECT m.model FROM messages m WHERE m.conversation_id = c.id "
            "   AND m.model IS NOT NULL ORDER BY m.created_at DESC LIMIT 1), w.default_model) "
            "FROM workspaces w WHERE w.tenant_id = c.tenant_id"
        )
    )
    bind.execute(sa.text("UPDATE messages SET reasoning = false WHERE role = 'assistant'"))
    for table in BACKFILL_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _create_tables()

    op.add_column("conversations", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.add_column("conversations", sa.Column("mode", sa.Text(), nullable=True))
    op.add_column("conversations", sa.Column("model", sa.Text(), nullable=True))
    op.add_column("conversations", sa.Column("reasoning", sa.Boolean(), nullable=True))
    op.add_column("messages", sa.Column("reasoning", sa.Boolean(), nullable=True))
    _backfill()
    for column in ("workspace_id", "mode", "model", "reasoning"):
        op.alter_column("conversations", column, nullable=False)
    op.create_foreign_key(
        op.f("fk_conversations_tenant_id_workspace_id_workspaces"),
        "conversations",
        "workspaces",
        ["tenant_id", "workspace_id"],
        ["tenant_id", "id"],
    )
    op.create_check_constraint(
        op.f("ck_conversations_mode_valid"), "conversations", f"mode IN {MODES}"
    )
    op.create_index(
        op.f("ix_conversations_tenant_id_workspace_id"),
        "conversations",
        ["tenant_id", "workspace_id"],
        unique=False,
    )
    op.drop_constraint(op.f("ck_messages_mode_valid"), "messages", type_="check")
    op.create_check_constraint(op.f("ck_messages_mode_valid"), "messages", f"mode IN {MODES}")

    op.execute(f"GRANT SELECT ON workspaces TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON workspace_prompts TO {APP_ROLE}")
    # Workspace, mode, model and reasoning are fixed when the conversation is created.
    op.execute(f"REVOKE UPDATE ON conversations FROM {APP_ROLE}")
    op.execute(f"GRANT UPDATE ({CONVERSATION_UPDATABLE}) ON conversations TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON workspaces TO {OPERATOR_ROLE}")
    op.execute(
        f"CREATE POLICY operator_console ON workspaces TO {OPERATOR_ROLE} "
        f"USING (true) WITH CHECK (true)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY operator_console ON workspaces")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON workspaces FROM {OPERATOR_ROLE}")
    op.execute(f"REVOKE UPDATE ({CONVERSATION_UPDATABLE}) ON conversations FROM {APP_ROLE}")
    op.execute(f"GRANT UPDATE ON conversations TO {APP_ROLE}")
    op.drop_constraint(op.f("ck_messages_mode_valid"), "messages", type_="check")
    # Revision 0006 knows only corpus-only answers; general-knowledge messages go.
    op.execute("ALTER TABLE messages NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM messages WHERE mode <> 'corpus_only'")
    op.execute("ALTER TABLE messages FORCE ROW LEVEL SECURITY")
    op.create_check_constraint(
        op.f("ck_messages_mode_valid"), "messages", "mode IN ('corpus_only')"
    )
    op.drop_index(op.f("ix_conversations_tenant_id_workspace_id"), table_name="conversations")
    op.drop_constraint(op.f("ck_conversations_mode_valid"), "conversations", type_="check")
    op.drop_constraint(
        op.f("fk_conversations_tenant_id_workspace_id_workspaces"),
        "conversations",
        type_="foreignkey",
    )
    op.drop_column("messages", "reasoning")
    for column in ("reasoning", "model", "mode", "workspace_id"):
        op.drop_column("conversations", column)
    op.drop_table("workspace_prompts")
    op.drop_table("workspaces")
