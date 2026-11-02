"""P2SR01-01: uploaded crawls, a site whose pages come from a ZIP of Markdown files.

- ``sites.origin``: ``crawl`` (the platform's crawler fetches it, P1b-04; every existing
  row) or ``upload`` (an editor uploads a crawl made outside the platform, a reviewer
  releases it, the worker imports it). Fixed at creation: a trigger refuses any change.
  An ``upload`` site has no schedule and never a next crawl (check ``upload_unscheduled``).
- ``sites.allow_decision`` gains ``declared``: for an uploaded crawl the robots, TDM and
  ``noai`` checks are the uploader's declaration, recorded per upload and released by a
  reviewer, not a check the platform makes (owner decision D3, Oct 31, 2026).
- ``site_uploads``: one row per uploaded ZIP. Who uploaded it and when, the crawl date
  (not after the upload date), full or partial (D5), the declaration (constrained true:
  it is the condition of the upload), the ZIP's SHA-256 and its staged copy under
  ``[files] content_root`` (``uploads/<sha256>.zip``, by hash), the inspection's counts,
  the status (``staged -> queued -> imported | failed``, or ``rejected``), the releasing
  or rejecting reviewer and note, an error code, and the import's counts. Counts and codes
  only: never a member name, URL or title. At most one ``staged`` or ``queued`` upload
  per site (D10, a partial unique index).
- ``jobs``: type ``import_crawl`` with payload key ``upload_id`` (required for that type,
  and part of the one-active-job-per-subject index).

``site_uploads`` is operator-owned and shared like ``sites`` (outside tenant RLS; it holds
no tenant data): the application role may read, insert and update it; the operator console
role has no grant, as for ``sites``.

The downgrade drops the uploads and the ``import_crawl`` jobs; upload sites stay as
``crawl`` sites with no schedule, and a ``declared`` decision becomes ``unchecked``.

Revision ID: 0080
Revises: 0065
Create Date: 2026-10-31 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

APP_ROLE = "askspore_app"
CODE = "'^[a-z][a-z0-9_]{0,39}$'"
OLD_DECISIONS = "('unchecked', 'allowed', 'robots_disallowed', 'tdm_reserved')"
NEW_DECISIONS = "('unchecked', 'allowed', 'robots_disallowed', 'tdm_reserved', 'declared')"
OLD_TYPES = "('ingest_source', 'withdraw_source', 'crawl_site', 'send_mail', 'purge_retention')"
NEW_TYPES = (
    "('ingest_source', 'withdraw_source', 'crawl_site', 'send_mail', 'purge_retention', "
    "'import_crawl')"
)
OLD_KEYS = (
    "ARRAY['source_id', 'site_id', 'add_tags', 'downloadable', 'parse_timeout', "
    "'template', 'tenant_id', 'user_id', 'notice_id']"
)
NEW_KEYS = (
    "ARRAY['source_id', 'site_id', 'add_tags', 'downloadable', 'parse_timeout', "
    "'template', 'tenant_id', 'user_id', 'notice_id', 'upload_id']"
)
OLD_SUBJECT = (
    "(type, (payload->>'source_id'), (payload->>'site_id'), "
    "(coalesce(payload->'add_tags', '[]'::jsonb)), (payload->>'template'), "
    "(payload->>'tenant_id'), (payload->>'user_id'), (payload->>'notice_id'))"
)
NEW_SUBJECT = (
    "(type, (payload->>'source_id'), (payload->>'site_id'), "
    "(coalesce(payload->'add_tags', '[]'::jsonb)), (payload->>'template'), "
    "(payload->>'tenant_id'), (payload->>'user_id'), (payload->>'notice_id'), "
    "(payload->>'upload_id'))"
)

revision: str = "0080"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _payload_check(keys: str) -> str:
    return (
        f"jsonb_typeof(payload) = 'object' AND (payload - {keys}) = '{{}}'::jsonb "
        "AND pg_column_size(payload) <= 2048"
    )


def _subject_index(columns: str) -> None:
    op.execute("DROP INDEX uq_jobs_one_active_per_subject")
    op.execute(
        f"CREATE UNIQUE INDEX uq_jobs_one_active_per_subject ON jobs {columns} "
        "NULLS NOT DISTINCT WHERE status IN ('queued', 'running')"
    )


def _count(name: str) -> sa.Column[int]:
    return sa.Column(name, sa.Integer(), server_default=sa.text("0"), nullable=False)


def upgrade() -> None:
    op.add_column(
        "sites", sa.Column("origin", sa.Text(), server_default=sa.text("'crawl'"), nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_sites_origin_valid"), "sites", "origin IN ('crawl', 'upload')"
    )
    op.create_check_constraint(
        op.f("ck_sites_upload_unscheduled"),
        "sites",
        "origin <> 'upload' OR (schedule = 'none' AND next_crawl_at IS NULL)",
    )
    op.execute(
        """
        CREATE FUNCTION sites_origin_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.origin IS DISTINCT FROM OLD.origin THEN
                RAISE EXCEPTION 'a site''s origin is fixed at creation'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER sites_origin_fixed BEFORE UPDATE OF origin ON sites "
        "FOR EACH ROW EXECUTE FUNCTION sites_origin_fixed()"
    )
    op.drop_constraint(op.f("ck_sites_allow_decision_valid"), "sites", type_="check")
    op.create_check_constraint(
        op.f("ck_sites_allow_decision_valid"), "sites", f"allow_decision IN {NEW_DECISIONS}"
    )

    op.create_table(
        "site_uploads",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("crawled_on", sa.Date(), nullable=False),
        sa.Column("mode", sa.Text(), server_default=sa.text("'partial'"), nullable=False),
        sa.Column("declared_robots_honoured", sa.Boolean(), nullable=False),
        sa.Column("zip_sha256", sa.Text(), nullable=False),
        sa.Column("staged_path", sa.Text(), nullable=True),
        _count("member_count"),
        _count("accepted_count"),
        _count("refused_count"),
        _count("skipped_count"),
        sa.Column("status", sa.Text(), server_default=sa.text("'staged'"), nullable=False),
        sa.Column("released_by", sa.UUID(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _count("new_count"),
        _count("changed_count"),
        _count("unchanged_count"),
        _count("blocked_count"),
        _count("withdrawn_count"),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("mode IN ('full', 'partial')", name=op.f("ck_site_uploads_mode_valid")),
        sa.CheckConstraint(
            "declared_robots_honoured", name=op.f("ck_site_uploads_declaration_made")
        ),
        sa.CheckConstraint(
            "zip_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_site_uploads_zip_sha256_hex")
        ),
        sa.CheckConstraint(
            "staged_path IS NULL OR staged_path = 'uploads/' || zip_sha256 || '.zip'",
            name=op.f("ck_site_uploads_staged_by_hash"),
        ),
        sa.CheckConstraint(
            "status IN ('staged', 'queued', 'imported', 'failed', 'rejected')",
            name=op.f("ck_site_uploads_status_valid"),
        ),
        sa.CheckConstraint(
            "crawled_on <= (uploaded_at AT TIME ZONE 'UTC')::date",
            name=op.f("ck_site_uploads_crawled_not_after_upload"),
        ),
        sa.CheckConstraint(
            "status IN ('staged', 'rejected') OR (released_by IS NOT NULL "
            "AND released_at IS NOT NULL)",
            name=op.f("ck_site_uploads_release_recorded"),
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR length(btrim(coalesce(review_note, ''))) > 0",
            name=op.f("ck_site_uploads_rejection_noted"),
        ),
        sa.CheckConstraint(
            f"(error IS NULL) = (status <> 'failed') AND (error IS NULL OR error ~ {CODE})",
            name=op.f("ck_site_uploads_error_when_failed"),
        ),
        sa.CheckConstraint(
            "least(member_count, accepted_count, refused_count, skipped_count, new_count, "
            "changed_count, unchanged_count, blocked_count, withdrawn_count) >= 0",
            name=op.f("ck_site_uploads_counts_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_site_uploads_site_id_sites")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_uploads")),
    )
    op.create_index(
        op.f("ix_site_uploads_site_id_uploaded_at"), "site_uploads", ["site_id", "uploaded_at"]
    )
    op.create_index(
        "uq_site_uploads_one_pending_per_site",
        "site_uploads",
        ["site_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('staged', 'queued')"),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON site_uploads TO {APP_ROLE}")

    op.drop_constraint(op.f("ck_jobs_type_valid"), "jobs", type_="check")
    op.create_check_constraint(op.f("ck_jobs_type_valid"), "jobs", f"type IN {NEW_TYPES}")
    op.drop_constraint(op.f("ck_jobs_payload_identifiers_only"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_payload_identifiers_only"), "jobs", _payload_check(NEW_KEYS)
    )
    op.create_check_constraint(
        op.f("ck_jobs_import_names_upload"),
        "jobs",
        "type <> 'import_crawl' OR payload ? 'upload_id'",
    )
    _subject_index(NEW_SUBJECT)


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE type = 'import_crawl'")
    _subject_index(OLD_SUBJECT)
    op.drop_constraint(op.f("ck_jobs_import_names_upload"), "jobs", type_="check")
    op.drop_constraint(op.f("ck_jobs_payload_identifiers_only"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_payload_identifiers_only"), "jobs", _payload_check(OLD_KEYS)
    )
    op.drop_constraint(op.f("ck_jobs_type_valid"), "jobs", type_="check")
    op.create_check_constraint(op.f("ck_jobs_type_valid"), "jobs", f"type IN {OLD_TYPES}")

    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON site_uploads FROM {APP_ROLE}")
    op.drop_index("uq_site_uploads_one_pending_per_site", table_name="site_uploads")
    op.drop_index(op.f("ix_site_uploads_site_id_uploaded_at"), table_name="site_uploads")
    op.drop_table("site_uploads")

    op.execute("UPDATE sites SET allow_decision = 'unchecked' WHERE allow_decision = 'declared'")
    op.drop_constraint(op.f("ck_sites_allow_decision_valid"), "sites", type_="check")
    op.create_check_constraint(
        op.f("ck_sites_allow_decision_valid"), "sites", f"allow_decision IN {OLD_DECISIONS}"
    )
    op.execute("DROP TRIGGER sites_origin_fixed ON sites")
    op.execute("DROP FUNCTION sites_origin_fixed()")
    op.drop_constraint(op.f("ck_sites_upload_unscheduled"), "sites", type_="check")
    op.drop_constraint(op.f("ck_sites_origin_valid"), "sites", type_="check")
    op.drop_column("sites", "origin")
