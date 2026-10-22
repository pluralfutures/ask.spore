"""P1b-03: re-ingestion and withdrawal.

- ``citations.superseded_at`` and ``citations.withdrawn_at``: set on stored citations
  when their source is re-ingested (its old chunks are gone) or withdrawn. The chat
  read routes return them as flags; the citation keeps its excerpt and provenance.
- ``sources.supersedes_id``: a proposal of a changed file (new hash, same canonical
  link as one ingested source) names the source it replaces. Once it is ingested, the
  old source is withdrawn from every dataset and its citations marked superseded.
- ``sources.takedown_requested_on`` and ``sources.takedown_due_on``: the takedown
  queue. The due date is 10 working days after the request, or the request date
  itself for a licence breach we find ourselves; both need ``takedown_reference``.
- ``askspore_content``: the role the withdrawal job runs as (``SET LOCAL ROLE``) to
  flag citations in every tenant's history and to list tenants for the cache purge.
  NOLOGIN, no BYPASSRLS; ``askspore_app`` may assume it but does not inherit it. It
  may read only the identifier and flag columns of ``citations`` (never the excerpt)
  and update only the two flags, and read ``tenants.id``; nothing else.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-21 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

APP_ROLE = "askspore_app"
CONTENT_ROLE = "askspore_content"

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "citations", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("citations", sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("supersedes_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_sources_supersedes_id_sources"), "sources", "sources", ["supersedes_id"], ["id"]
    )
    op.create_check_constraint(
        op.f("ck_sources_supersedes_another"), "sources", "supersedes_id IS DISTINCT FROM id"
    )
    op.add_column("sources", sa.Column("takedown_requested_on", sa.Date(), nullable=True))
    op.add_column("sources", sa.Column("takedown_due_on", sa.Date(), nullable=True))
    op.create_check_constraint(
        op.f("ck_sources_takedown_recorded"),
        "sources",
        "(takedown_requested_on IS NULL AND takedown_due_on IS NULL) OR "
        "(length(btrim(coalesce(takedown_reference, ''))) > 0 "
        "AND takedown_requested_on IS NOT NULL "
        "AND takedown_due_on >= takedown_requested_on)",
    )
    op.create_index(op.f("ix_sources_takedown_due_on"), "sources", ["takedown_due_on"])

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{CONTENT_ROLE}') THEN
                CREATE ROLE {CONTENT_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            ELSIF EXISTS (
                SELECT FROM pg_roles
                WHERE rolname = '{CONTENT_ROLE}' AND (rolsuper OR rolbypassrls OR rolcanlogin)
            ) THEN
                RAISE EXCEPTION '{CONTENT_ROLE} must be NOLOGIN and must not bypass RLS';
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT {CONTENT_ROLE} TO {APP_ROLE} WITH INHERIT FALSE, SET TRUE")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {CONTENT_ROLE}")
    op.execute(
        "GRANT SELECT (id, tenant_id, source_id, superseded_at, withdrawn_at) "
        f"ON citations TO {CONTENT_ROLE}"
    )
    op.execute(f"GRANT UPDATE (superseded_at, withdrawn_at) ON citations TO {CONTENT_ROLE}")
    op.execute(
        f"CREATE POLICY content_flags_read ON citations FOR SELECT TO {CONTENT_ROLE} USING (true)"
    )
    op.execute(
        f"CREATE POLICY content_flags ON citations FOR UPDATE TO {CONTENT_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(f"GRANT SELECT (id) ON tenants TO {CONTENT_ROLE}")
    op.execute(f"CREATE POLICY content_purge ON tenants FOR SELECT TO {CONTENT_ROLE} USING (true)")


def downgrade() -> None:
    op.execute("DROP POLICY content_purge ON tenants")
    op.execute(f"REVOKE SELECT (id) ON tenants FROM {CONTENT_ROLE}")
    op.execute("DROP POLICY content_flags ON citations")
    op.execute("DROP POLICY content_flags_read ON citations")
    op.execute(f"REVOKE UPDATE (superseded_at, withdrawn_at) ON citations FROM {CONTENT_ROLE}")
    op.execute(
        "REVOKE SELECT (id, tenant_id, source_id, superseded_at, withdrawn_at) "
        f"ON citations FROM {CONTENT_ROLE}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {CONTENT_ROLE}")
    # The role is cluster-wide (like askspore_app) and is kept; only its membership goes.
    op.execute(f"REVOKE {CONTENT_ROLE} FROM {APP_ROLE}")
    op.drop_index(op.f("ix_sources_takedown_due_on"), table_name="sources")
    op.drop_constraint(op.f("ck_sources_takedown_recorded"), "sources", type_="check")
    op.drop_column("sources", "takedown_due_on")
    op.drop_column("sources", "takedown_requested_on")
    op.drop_constraint(op.f("ck_sources_supersedes_another"), "sources", type_="check")
    op.drop_constraint(op.f("fk_sources_supersedes_id_sources"), "sources", type_="foreignkey")
    op.drop_column("sources", "supersedes_id")
    op.drop_column("citations", "withdrawn_at")
    op.drop_column("citations", "superseded_at")
