"""P0-09: ingestion results on the source register.

P0-09 records each source's chunk count and, on failure, the error. Schema v1 has
no columns for either, so this adds:

- ``sources.chunk_count``: total chunks across the source's RAGFlow documents;
- ``sources.error``: why ingestion failed, set only while ``status = 'failed'``.

``sources.ragflow_document_ids`` keeps the shape ``{ragflow_dataset_id:
ragflow_document_id}``. ``sources`` is shared corpus metadata, not tenant-scoped,
so it has no row-level security.

MERGE NOTE: numbered 0003 because Group C's 0002 (messages.outcome) is on another
branch. Until those branches meet, this revises 0001; when they merge, set
``down_revision = "0002"`` so the history stays linear.

Revision ID: 0003
Revises: 0001
Create Date: 2026-10-17 23:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("chunk_count", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("error", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_sources_error_only_when_failed"), "sources", "error IS NULL OR status = 'failed'"
    )
    op.create_check_constraint(
        op.f("ck_sources_chunk_count_non_negative"), "sources", "chunk_count >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_sources_chunk_count_non_negative"), "sources", type_="check")
    op.drop_constraint(op.f("ck_sources_error_only_when_failed"), "sources", type_="check")
    op.drop_column("sources", "error")
    op.drop_column("sources", "chunk_count")
