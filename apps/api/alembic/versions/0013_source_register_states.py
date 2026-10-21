"""P1b-01: source register states and content roles.

- ``sources.status`` becomes ``proposed -> approved -> ingested -> withdrawn``, plus
  ``failed`` (retryable: a reviewer sends it back to ``approved``) and ``rejected`` (a
  reviewer declined the proposal; findings 1b §1). The Phase 0 values go: a
  ``registered`` row becomes ``proposed``, an ``ingesting`` row (an ingestion that
  never finished) becomes ``failed``.
- New register columns: ``proposed_by``, ``approved_by``, ``approved_at``,
  ``withdrawn_at``, ``withdrawal_reason``, ``takedown_reference``, ``review_date``,
  ``licence_file_path`` and ``review_note`` (the reviewer's note on approval or
  rejection). ``proposed_by`` and ``approved_by`` name users of the internal tenant;
  like ``audit_events.actor_user_id`` they have no foreign key, so the register keeps
  its history when a user goes. Rows ingested before this revision have no proposer or
  approver; their ``approved_at`` is set to their last update.
- ``licence_file_path``: a licence or permission letter under ``[files] content_root``,
  stored by hash as ``licences/<sha256>.<ext>``; never uploaded to RAGFlow.
- ``content_roles``: ``content_editor`` (propose, upload, register sites) and
  ``content_reviewer`` (approve, reject, withdraw) for users of the internal tenant.
  It carries ``tenant_id``, pinned to the internal tenant, so it gets forced RLS and a
  ``tenant_id``-first key like every table with a ``tenant_id``. Granted with
  ``ask-spore content-roles grant`` as the schema owner; the application role may only
  read it (inside the internal tenant's scope), to check a role.

``sources`` stays the operator-owned shared register, outside tenant RLS.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-21 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

APP_ROLE = "askspore_app"
INTERNAL_TENANT_ID = "00000000-0000-4000-8000-000000000001"
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
OLD_STATUSES = "('registered', 'ingesting', 'ingested', 'failed', 'withdrawn')"
NEW_STATUSES = "('proposed', 'approved', 'ingested', 'failed', 'withdrawn', 'rejected')"

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_sources_status_valid"), "sources", type_="check")
    op.execute(
        "UPDATE sources SET status = 'failed', "
        "error = coalesce(error, 'ingestion did not finish (before Phase 1b)') "
        "WHERE status = 'ingesting'"
    )
    op.execute("UPDATE sources SET status = 'proposed' WHERE status = 'registered'")
    op.alter_column("sources", "status", server_default=sa.text("'proposed'"))
    op.create_check_constraint(
        op.f("ck_sources_status_valid"), "sources", f"status IN {NEW_STATUSES}"
    )

    for name, type_ in (
        ("proposed_by", sa.UUID()),
        ("approved_by", sa.UUID()),
        ("approved_at", sa.DateTime(timezone=True)),
        ("withdrawn_at", sa.DateTime(timezone=True)),
        ("withdrawal_reason", sa.Text()),
        ("takedown_reference", sa.Text()),
        ("review_date", sa.Date()),
        ("licence_file_path", sa.Text()),
        ("review_note", sa.Text()),
    ):
        op.add_column("sources", sa.Column(name, type_, nullable=True))

    op.execute(
        "UPDATE sources SET approved_at = updated_at "
        "WHERE status IN ('approved', 'ingested', 'failed', 'withdrawn')"
    )
    op.execute(
        "UPDATE sources SET withdrawn_at = updated_at, "
        "withdrawal_reason = 'withdrawn before Phase 1b' WHERE status = 'withdrawn'"
    )
    op.create_check_constraint(
        op.f("ck_sources_approval_recorded"),
        "sources",
        "status IN ('proposed', 'rejected') OR approved_at IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_sources_withdrawal_recorded"),
        "sources",
        "status <> 'withdrawn' OR (withdrawn_at IS NOT NULL "
        "AND length(btrim(withdrawal_reason)) > 0)",
    )
    op.create_check_constraint(
        op.f("ck_sources_licence_file_by_hash"),
        "sources",
        "licence_file_path IS NULL OR licence_file_path ~ '^licences/[0-9a-f]{64}\\.[a-z0-9]{1,8}$'",
    )

    op.create_table(
        "content_roles",
        sa.Column(
            "tenant_id",
            sa.UUID(),
            server_default=sa.text(f"'{INTERNAL_TENANT_ID}'::uuid"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"tenant_id = '{INTERNAL_TENANT_ID}'::uuid",
            name=op.f("ck_content_roles_internal_tenant"),
        ),
        sa.CheckConstraint(
            "role IN ('content_editor', 'content_reviewer')", name=op.f("ck_content_roles_role_valid")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_content_roles_tenant_id_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_content_roles_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", "role", name=op.f("pk_content_roles")),
    )
    predicate = f"tenant_id = {CURRENT_TENANT}"
    op.execute("ALTER TABLE content_roles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE content_roles FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON content_roles "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )
    op.execute(f"GRANT SELECT ON content_roles TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ON content_roles FROM {APP_ROLE}")
    op.drop_table("content_roles")
    for name in ("licence_file_by_hash", "withdrawal_recorded", "approval_recorded"):
        op.drop_constraint(op.f(f"ck_sources_{name}"), "sources", type_="check")
    for name in (
        "review_note",
        "licence_file_path",
        "review_date",
        "takedown_reference",
        "withdrawal_reason",
        "withdrawn_at",
        "approved_at",
        "approved_by",
        "proposed_by",
    ):
        op.drop_column("sources", name)
    op.drop_constraint(op.f("ck_sources_status_valid"), "sources", type_="check")
    op.execute("UPDATE sources SET status = 'registered' WHERE status = 'proposed'")
    op.execute("UPDATE sources SET status = 'failed' WHERE status IN ('approved', 'rejected')")
    op.alter_column("sources", "status", server_default=sa.text("'registered'"))
    op.create_check_constraint(
        op.f("ck_sources_status_valid"), "sources", f"status IN {OLD_STATUSES}"
    )
