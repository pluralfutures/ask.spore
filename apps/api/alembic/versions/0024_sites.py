"""P1b-04: crawl management.

- ``sites``: one row per registered website: start URL and host, the metadata its pages
  get (name, publisher, licence basis, tags), scope rules (path allow and deny
  patterns), schedule (none, weekly, monthly), page budget, the reviewer's whitelist of
  paths exempt from the special-category skip, the register states of a site
  (``proposed -> approved``, or ``rejected``, with proposer, approver and note), the
  per-site allow decision from robots.txt and the TDM reservation, and the last crawl
  (date, outcome, live page count, next due date).
- ``site_pages``: one row per page URL a crawl met: ``live`` (a register row, the page's
  current version), ``blocked`` (with the reason, and the special category when that
  was it) or ``removed`` (gone from the site). Blocked pages are listed in the console.
- ``sources.site_id``, ``sources.snapshot_path`` and ``sources.fetched_at``: a crawled
  page's register row names its site, the raw HTML snapshot kept for provenance under
  ``[files] content_root`` as ``snapshots/<sha256>.html``, and when it was fetched.

Like ``sources`` these are operator-owned shared tables, outside tenant RLS (no tenant
data); the application role (API, CLI, worker) may read, insert and update them.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-22 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = "askspore_app"
CODE = "'^[a-z][a-z0-9_]{0,39}$'"

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    text_array = postgresql.ARRAY(sa.Text())
    empty = sa.text("'{}'::text[]")
    op.create_table(
        "sites",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("start_url", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("licence_basis", sa.Text(), nullable=False),
        sa.Column("tags", text_array, server_default=empty, nullable=False),
        sa.Column("allow_patterns", text_array, server_default=empty, nullable=False),
        sa.Column("deny_patterns", text_array, server_default=empty, nullable=False),
        sa.Column("special_category_allow", text_array, server_default=empty, nullable=False),
        sa.Column("schedule", sa.Text(), server_default=sa.text("'none'"), nullable=False),
        sa.Column("max_pages", sa.Integer(), server_default=sa.text("50"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'proposed'"), nullable=False),
        sa.Column(
            "allow_decision", sa.Text(), server_default=sa.text("'unchecked'"), nullable=False
        ),
        sa.Column("allow_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_crawl_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_crawl_status", sa.Text(), nullable=True),
        sa.Column("next_crawl_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("page_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("proposed_by", sa.UUID(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
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
        sa.CheckConstraint("start_url ~ '^https?://'", name=op.f("ck_sites_start_url_http")),
        sa.CheckConstraint("cardinality(tags) >= 1", name=op.f("ck_sites_has_tags")),
        sa.CheckConstraint(
            "schedule IN ('none', 'weekly', 'monthly')", name=op.f("ck_sites_schedule_valid")
        ),
        sa.CheckConstraint("max_pages BETWEEN 1 AND 5000", name=op.f("ck_sites_max_pages_range")),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected')", name=op.f("ck_sites_status_valid")
        ),
        sa.CheckConstraint(
            "status <> 'approved' OR approved_at IS NOT NULL",
            name=op.f("ck_sites_approval_recorded"),
        ),
        sa.CheckConstraint(
            "allow_decision IN ('unchecked', 'allowed', 'robots_disallowed', 'tdm_reserved')",
            name=op.f("ck_sites_allow_decision_valid"),
        ),
        sa.CheckConstraint(
            f"last_crawl_status IS NULL OR last_crawl_status ~ {CODE}",
            name=op.f("ck_sites_last_crawl_status_code"),
        ),
        sa.CheckConstraint("page_count >= 0", name=op.f("ck_sites_page_count_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sites")),
        sa.UniqueConstraint("start_url", name=op.f("uq_sites_start_url")),
    )
    op.create_index(op.f("ix_sites_status_next_crawl_at"), "sites", ["status", "next_crawl_at"])

    op.create_table(
        "site_pages",
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("special_category", sa.Text(), nullable=True),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('live', 'blocked', 'removed')", name=op.f("ck_site_pages_state_valid")
        ),
        sa.CheckConstraint(
            f"(state = 'live') = (reason IS NULL) AND (reason IS NULL OR reason ~ {CODE})",
            name=op.f("ck_site_pages_reason_when_not_live"),
        ),
        sa.CheckConstraint(
            "state <> 'live' OR source_id IS NOT NULL", name=op.f("ck_site_pages_live_has_source")
        ),
        sa.CheckConstraint(
            f"special_category IS NULL OR special_category ~ {CODE}",
            name=op.f("ck_site_pages_special_category_code"),
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_site_pages_site_id_sites"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name=op.f("fk_site_pages_source_id_sources")
        ),
        sa.PrimaryKeyConstraint("site_id", "url", name=op.f("pk_site_pages")),
    )
    op.create_index(op.f("ix_site_pages_source_id"), "site_pages", ["source_id"])

    op.add_column("sources", sa.Column("site_id", sa.UUID(), nullable=True))
    op.add_column("sources", sa.Column("snapshot_path", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(op.f("fk_sources_site_id_sites"), "sources", "sites", ["site_id"], ["id"])
    op.create_index(op.f("ix_sources_site_id"), "sources", ["site_id"])
    op.create_check_constraint(
        op.f("ck_sources_snapshot_by_hash"),
        "sources",
        "snapshot_path IS NULL OR snapshot_path ~ '^snapshots/[0-9a-f]{64}\\.html$'",
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON sites, site_pages TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON sites, site_pages FROM {APP_ROLE}")
    op.drop_constraint(op.f("ck_sources_snapshot_by_hash"), "sources", type_="check")
    op.drop_index(op.f("ix_sources_site_id"), table_name="sources")
    op.drop_constraint(op.f("fk_sources_site_id_sites"), "sources", type_="foreignkey")
    op.drop_column("sources", "fetched_at")
    op.drop_column("sources", "snapshot_path")
    op.drop_column("sources", "site_id")
    op.drop_index(op.f("ix_site_pages_source_id"), table_name="site_pages")
    op.drop_table("site_pages")
    op.drop_index(op.f("ix_sites_status_next_crawl_at"), table_name="sites")
    op.drop_table("sites")
