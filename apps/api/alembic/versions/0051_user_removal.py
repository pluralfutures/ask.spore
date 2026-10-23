"""P1c-07: removing one user's account data and history.

- A new NOLOGIN role **``askspore_user_removal``**, which the application role may
  assume for one transaction (``SET LOCAL ROLE``) but does not inherit, as for the
  retention role (revision 0040). The tenant admin's and the operator's "remove user"
  routes take it after their own checks (``app.tenancy.user_removal``). Per table it may
  read only the columns its deletions filter on (IDs, the user's role and status) and
  delete: the user's conversations with their messages, citations and feedback, their
  feedback on other messages, download records, revoked sessions, sign-in links, MFA
  challenges and the ``users`` row itself. It has no policy of its own on the tenant
  tables, so their ``tenant_isolation`` policies apply: with ``app.tenant_id`` set it
  reaches one tenant's rows only. It reads ``operators`` and ``content_roles`` (to refuse
  a user holding a platform role) and the register's ``proposed_by`` and ``approved_by``.
- ``workspace_prompts.author_user_id`` becomes nullable: a removed user's prompt
  versions stay (they are the workspace's), without their author. The role may set that
  column to NULL and nothing else.
- ``jobs``: the role may delete the jobs whose payload names the user (their invitation
  and consent-notice mail) and clear ``created_by`` where the user queued one. Its
  ``user_removal`` policy scopes it to jobs whose payload names the tenant in
  ``app.tenant_id``; inert while ``jobs`` has no row-level security, in force once it has
  (P1c-04).

``audit_events`` (append-only) and ``usage_ledger`` (no user column) are kept.

Revision ID: 0051
Revises: 0050
Create Date: 2026-10-23 13:00:00
"""

from collections.abc import Sequence

from alembic import op

APP_ROLE = "askspore_app"
REMOVAL_ROLE = "askspore_user_removal"
# What the role may read (only to filter its deletions) and delete, per table.
DELETABLE = {
    "conversations": "id, tenant_id, user_id",
    "messages": "id, tenant_id, conversation_id",
    "citations": "id, tenant_id, message_id",
    "feedback": "id, tenant_id, message_id, user_id",
    "downloads": "id, tenant_id, user_id",
    "revoked_sessions": "tenant_id, user_id",
    "sign_in_links": "id, tenant_id, user_id",
    "mfa_challenges": "id, tenant_id, user_id",
    "users": "id, tenant_id, role, status",
}
READABLE = {
    "operators": "tenant_id, user_id",
    "content_roles": "tenant_id, user_id",
    "sources": "proposed_by, approved_by",
    "sites": "proposed_by, approved_by",
    "workspace_prompts": "id, tenant_id, author_user_id",
}

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("workspace_prompts", "author_user_id", nullable=True)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{REMOVAL_ROLE}') THEN
                CREATE ROLE {REMOVAL_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB
                    NOCREATEROLE;
            ELSIF EXISTS (
                SELECT FROM pg_roles
                WHERE rolname = '{REMOVAL_ROLE}' AND (rolsuper OR rolbypassrls OR rolcanlogin)
            ) THEN
                RAISE EXCEPTION '{REMOVAL_ROLE} must be NOLOGIN and must not bypass RLS';
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT {REMOVAL_ROLE} TO {APP_ROLE} WITH INHERIT FALSE, SET TRUE")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {REMOVAL_ROLE}")
    for table, columns in DELETABLE.items():
        op.execute(f"GRANT SELECT ({columns}), DELETE ON {table} TO {REMOVAL_ROLE}")
    for table, columns in READABLE.items():
        op.execute(f"GRANT SELECT ({columns}) ON {table} TO {REMOVAL_ROLE}")
    op.execute(f"GRANT UPDATE (author_user_id) ON workspace_prompts TO {REMOVAL_ROLE}")
    op.execute(f"GRANT SELECT (id, payload, created_by), DELETE ON jobs TO {REMOVAL_ROLE}")
    op.execute(f"GRANT UPDATE (created_by) ON jobs TO {REMOVAL_ROLE}")
    op.execute(
        f"CREATE POLICY user_removal ON jobs TO {REMOVAL_ROLE} "
        "USING (payload->>'tenant_id' = current_setting('app.tenant_id', true)) "
        "WITH CHECK (payload->>'tenant_id' = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY user_removal ON jobs")
    op.execute(f"REVOKE UPDATE (created_by) ON jobs FROM {REMOVAL_ROLE}")
    op.execute(f"REVOKE SELECT (id, payload, created_by), DELETE ON jobs FROM {REMOVAL_ROLE}")
    op.execute(f"REVOKE UPDATE (author_user_id) ON workspace_prompts FROM {REMOVAL_ROLE}")
    for table, columns in READABLE.items():
        op.execute(f"REVOKE SELECT ({columns}) ON {table} FROM {REMOVAL_ROLE}")
    for table, columns in DELETABLE.items():
        op.execute(f"REVOKE SELECT ({columns}), DELETE ON {table} FROM {REMOVAL_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {REMOVAL_ROLE}")
    # The role is cluster-wide (like askspore_app) and is kept; only its membership goes.
    op.execute(f"REVOKE {REMOVAL_ROLE} FROM {APP_ROLE}")
    # A prompt version whose author was removed cannot get one back: it goes.
    op.execute("DELETE FROM workspace_prompts WHERE author_user_id IS NULL")
    op.alter_column("workspace_prompts", "author_user_id", nullable=False)
