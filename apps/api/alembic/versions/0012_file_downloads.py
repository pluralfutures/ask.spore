"""P1a-14: workspace file list and downloads.

- ``sources.downloadable`` (boolean, not null, default false): the licence gate
  (compliance addendum, revised Oct 19, 2026). Set per source from the ingestion
  manifest's ``downloadable`` column and toggled by the operator (audited).
- ``sources.stored_path``: where our own copy of an ingested PDF, DOCX or PPTX file
  lies under ``[files] content_root``, named by its SHA-256 (``ab/<sha256>.pdf``), never
  by the original file name. Downloads read this copy and check its hash; RAGFlow is
  never asked for a file. Null for pages and for files ingested before this revision
  (re-running the manifest stores them, findings D10). A check constraint keeps the
  path to that shape and consistent with ``file_sha256``, so it cannot point elsewhere.
- ``downloads``: one row per download link issued, tenant-scoped (forced RLS,
  ``tenant_id``-first index ``(tenant_id, user_id, created_at)`` for the daily cap).
  Only the SHA-256 of the link token is stored; ``expires_at`` is at most five minutes
  after issue; ``served_at`` makes the link single-use. The application role may
  read, insert and set ``served_at``; no delete.
- The operator role (revision 0006) may now read the register columns the console
  shows and update ``downloadable`` only. It still cannot read
  ``ragflow_document_ids``, so ``SELECT *`` on ``sources`` stays refused.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-19 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

APP_ROLE = "askspore_app"
OPERATOR_ROLE = "askspore_operator"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
OPERATOR_SOURCE_COLUMNS = (
    "id, type, title, publisher, published_on, licence_basis, tags, status, "
    "file_sha256, stored_path, downloadable, created_at"
)

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("downloadable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("sources", sa.Column("stored_path", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_sources_stored_path_by_hash"),
        "sources",
        "stored_path IS NULL OR (type IN ('pdf', 'docx', 'pptx') AND stored_path = "
        "substr(file_sha256, 1, 2) || '/' || file_sha256 || '.' || type)",
    )

    op.create_table(
        "downloads",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("token_sha256", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("served_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "token_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_downloads_token_sha256_hex")
        ),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '5 minutes'", name=op.f("ck_downloads_expiry_cap")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_downloads_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_downloads_tenant_id_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workspace_id"],
            ["workspaces.tenant_id", "workspaces.id"],
            name=op.f("fk_downloads_tenant_id_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_downloads_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_downloads")),
        sa.UniqueConstraint("token_sha256", name=op.f("uq_downloads_token_sha256")),
    )
    op.create_index(
        op.f("ix_downloads_tenant_id_user_id_created_at"),
        "downloads",
        ["tenant_id", "user_id", "created_at"],
    )
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute("ALTER TABLE downloads ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE downloads FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON downloads USING ({predicate}) WITH CHECK ({predicate})"
    )
    op.execute(f"GRANT SELECT, INSERT ON downloads TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (served_at) ON downloads TO {APP_ROLE}")

    op.execute(f"GRANT SELECT ({OPERATOR_SOURCE_COLUMNS}) ON sources TO {OPERATOR_ROLE}")
    op.execute(f"GRANT UPDATE (downloadable, updated_at) ON sources TO {OPERATOR_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE (downloadable, updated_at) ON sources FROM {OPERATOR_ROLE}")
    op.execute(f"REVOKE SELECT ({OPERATOR_SOURCE_COLUMNS}) ON sources FROM {OPERATOR_ROLE}")
    op.drop_table("downloads")
    op.drop_constraint(op.f("ck_sources_stored_path_by_hash"), "sources", type_="check")
    op.drop_column("sources", "stored_path")
    op.drop_column("sources", "downloadable")
