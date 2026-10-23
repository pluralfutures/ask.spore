"""P1c-04: row-level security on ``jobs``, scoped by the payload's tenant.

The independent review of Oct 22, 2026 (P1b-16) ruled ``jobs`` acceptable without RLS
while no tenant-facing route reads it, and gave the fix for before the first client
user: since 0030 ``send_mail`` jobs carry ``tenant_id`` and ``user_id`` in the payload,
so a tenant-scoped session must not read another tenant's jobs.

- RLS enabled and forced on ``jobs``.
- ``tenant_scope`` (every role with a grant: the application role, and the schema
  owner when it is not a superuser): a session scoped to a tenant (``app.tenant_id``
  set) sees and writes only jobs whose payload names that tenant or no tenant (content,
  crawl, purge and operator-notice jobs); an unscoped session (the worker, the CLI, the
  termination purge before it scopes) sees all, as before.
- ``operator_console`` (``askspore_operator``): all jobs, scoped or not, as before (it
  may read and add, 0030).

The table stays operator-owned and shared: it has no ``tenant_id`` column, so it is
not one of ``test_schema.TENANT_TABLES``; ``tests/test_jobs.py`` proves the negative case.

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-23 12:00:00
"""

from collections.abc import Sequence

from alembic import op

OPERATOR_ROLE = "askspore_operator"
SCOPE = (
    "payload->>'tenant_id' IS NULL "
    "OR NULLIF(current_setting('app.tenant_id', true), '') IS NULL "
    "OR payload->>'tenant_id' = current_setting('app.tenant_id', true)"
)

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE jobs FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_scope ON jobs USING ({SCOPE}) WITH CHECK ({SCOPE})")
    op.execute(
        f"CREATE POLICY operator_console ON jobs TO {OPERATOR_ROLE} USING (true) WITH CHECK (true)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY operator_console ON jobs")
    op.execute("DROP POLICY tenant_scope ON jobs")
    op.execute("ALTER TABLE jobs NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE jobs DISABLE ROW LEVEL SECURITY")
