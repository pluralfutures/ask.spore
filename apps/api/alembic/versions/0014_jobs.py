"""P1b-02: the background job queue.

``jobs`` holds the work of the ``worker`` Compose service (``ask-spore worker``):
``ingest_source``, ``withdraw_source`` and ``crawl_site``. Like the source register it
is operator-owned and shared, outside tenant RLS: no job carries tenant data.

- ``payload`` holds identifiers and settings only, never document contents: a check
  constraint allows the keys ``source_id``, ``site_id``, ``add_tags``,
  ``downloadable`` and ``parse_timeout`` and nothing else, and caps its size.
- The outcome is ``status`` and ``error_code`` only (a short identifier, checked), so no
  error text, title or body can be stored here.
- ``attempts``, ``max_attempts`` and ``run_after`` give retries with backoff;
  ``locked_until`` is the running worker's lease, renewed while it works, so a job
  whose worker died is picked up again.
- A partial unique index allows one queued or running job per type and source (and
  set of added tags), so an approval enqueues exactly one job however often it is sent.
- The application role (API, CLI, worker) may read, insert and update; no delete.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-21 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = "askspore_app"
PAYLOAD_KEYS = "ARRAY['source_id', 'site_id', 'add_tags', 'downloadable', 'parse_timeout']"

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "type IN ('ingest_source', 'withdraw_source', 'crawl_site')",
            name=op.f("ck_jobs_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_jobs_status_valid"),
        ),
        sa.CheckConstraint(
            f"jsonb_typeof(payload) = 'object' AND (payload - {PAYLOAD_KEYS}) = '{{}}'::jsonb "
            "AND pg_column_size(payload) <= 2048",
            name=op.f("ck_jobs_payload_identifiers_only"),
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z0-9_]{1,64}$'",
            name=op.f("ck_jobs_error_code_format"),
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR error_code IS NULL", name=op.f("ck_jobs_no_error_on_success")
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1 AND attempts <= max_attempts",
            name=op.f("ck_jobs_attempts_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_status_run_after"), "jobs", ["status", "run_after"])
    op.execute(
        "CREATE UNIQUE INDEX uq_jobs_one_active_per_subject ON jobs "
        "(type, (payload->>'source_id'), (payload->>'site_id'), "
        "(coalesce(payload->'add_tags', '[]'::jsonb))) NULLS NOT DISTINCT "
        "WHERE status IN ('queued', 'running')"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON jobs TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON jobs FROM {APP_ROLE}")
    op.drop_table("jobs")
