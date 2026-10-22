"""P1b-14: the retention purge job and a "no history" retention of 0 days.

- ``jobs.type`` gains ``purge_retention``: the worker queues one a day (and the CLI on
  demand, ``ask-spore purge --run``). Its payload is empty.
- A new NOLOGIN role **``askspore_retention``**, which the application role may assume
  for one transaction (``SET LOCAL ROLE``) but does not inherit, as for the content and
  operator roles. It may list tenant IDs (its own ``SELECT`` policy on ``tenants``) and,
  per tenant, with ``app.tenant_id`` set, delete conversations, messages, citations and
  feedback, ``revoked_sessions`` rows and ``downloads`` rows. It reads only the columns
  those deletions filter on (IDs, ``expires_at``, ``created_at``), never a message,
  excerpt or comment. It has no policy of its own on the tenant tables, so their
  ``tenant_isolation`` policies apply to it as to everyone: a purge deletes only rows
  of the tenant it is scoped to.
- ``tenant_settings.retention_days`` may be 0 ("no history", architecture §7.2): the
  conversation lives only while its answer streams.

Revision ID: 0040
Revises: 0031
Create Date: 2026-10-22 16:00:00

Numbered from 0040 on 0031 because Group E1 adds 0032 in parallel; the integration step
re-parents this revision (one ``down_revision`` line).
"""

from collections.abc import Sequence

from alembic import op

APP_ROLE = "askspore_app"
RETENTION_ROLE = "askspore_retention"
OLD_TYPES = "('ingest_source', 'withdraw_source', 'crawl_site', 'send_mail')"
NEW_TYPES = "('ingest_source', 'withdraw_source', 'crawl_site', 'send_mail', 'purge_retention')"
# What the role may read (only to filter its deletions) and delete, per table.
READABLE = {
    "conversations": "id, tenant_id, created_at, expires_at",
    "messages": "id, tenant_id, conversation_id",
    "citations": "id, tenant_id, message_id",
    "feedback": "id, tenant_id, message_id",
    "revoked_sessions": "tenant_id, token_sha256, expires_at",
    "downloads": "id, tenant_id, created_at",
}

revision: str = "0040"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_jobs_type_valid"), "jobs", type_="check")
    op.create_check_constraint(op.f("ck_jobs_type_valid"), "jobs", f"type IN {NEW_TYPES}")

    op.drop_constraint(op.f("ck_tenant_settings_retention_cap"), "tenant_settings", type_="check")
    op.create_check_constraint(
        op.f("ck_tenant_settings_retention_cap"),
        "tenant_settings",
        "retention_days BETWEEN 0 AND 30",
    )

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{RETENTION_ROLE}') THEN
                CREATE ROLE {RETENTION_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB
                    NOCREATEROLE;
            ELSIF EXISTS (
                SELECT FROM pg_roles
                WHERE rolname = '{RETENTION_ROLE}' AND (rolsuper OR rolbypassrls OR rolcanlogin)
            ) THEN
                RAISE EXCEPTION '{RETENTION_ROLE} must be NOLOGIN and must not bypass RLS';
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT {RETENTION_ROLE} TO {APP_ROLE} WITH INHERIT FALSE, SET TRUE")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {RETENTION_ROLE}")
    for table, columns in READABLE.items():
        op.execute(f"GRANT SELECT ({columns}), DELETE ON {table} TO {RETENTION_ROLE}")
    op.execute(f"GRANT SELECT (id) ON tenants TO {RETENTION_ROLE}")
    op.execute(
        f"CREATE POLICY retention_purge ON tenants FOR SELECT TO {RETENTION_ROLE} USING (true)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY retention_purge ON tenants")
    op.execute(f"REVOKE SELECT (id) ON tenants FROM {RETENTION_ROLE}")
    for table, columns in READABLE.items():
        op.execute(f"REVOKE SELECT ({columns}), DELETE ON {table} FROM {RETENTION_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {RETENTION_ROLE}")
    # The role is cluster-wide (like askspore_app) and is kept; only its membership goes.
    op.execute(f"REVOKE {RETENTION_ROLE} FROM {APP_ROLE}")

    op.execute("UPDATE tenant_settings SET retention_days = 1 WHERE retention_days = 0")
    op.drop_constraint(op.f("ck_tenant_settings_retention_cap"), "tenant_settings", type_="check")
    op.create_check_constraint(
        op.f("ck_tenant_settings_retention_cap"),
        "tenant_settings",
        "retention_days BETWEEN 1 AND 30",
    )

    op.execute("DELETE FROM jobs WHERE type = 'purge_retention'")
    op.drop_constraint(op.f("ck_jobs_type_valid"), "jobs", type_="check")
    op.create_check_constraint(op.f("ck_jobs_type_valid"), "jobs", f"type IN {OLD_TYPES}")
