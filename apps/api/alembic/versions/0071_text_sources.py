"""P2B-06: Markdown and plain-text files as stored, downloadable sources.

- ``sources.type`` gains ``text`` (a ``.txt`` file). ``markdown`` already exists, for crawled
  pages and for uploaded ``.md`` files.
- ``stored_path_by_hash`` now also allows ``markdown`` and ``text``: an uploaded Markdown or
  text file keeps our own copy for downloads, named by its hash like a PDF, DOCX or PPTX.
  A crawled page still has no stored path; the file/page split is by origin (stored copy or
  not), not by type, so no existing row changes.

No grants change. The downgrade refuses to run while a ``text`` source exists, rather than
deleting a document; remove or re-type those first. Stored paths of Markdown files are
cleared on downgrade (the copy stays in the content store).

Revision ID: 0071
Revises: 0065
Create Date: 2026-10-27 12:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0071"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPES = "('pdf', 'docx', 'pptx', 'html', 'markdown')"
NEW_TYPES = "('pdf', 'docx', 'pptx', 'html', 'markdown', 'text')"
STORED_PATH = (
    "stored_path IS NULL OR (type IN {types} AND stored_path = "
    "substr(file_sha256, 1, 2) || '/' || file_sha256 || '.' || type)"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_sources_type_valid"), "sources", type_="check")
    op.create_check_constraint(op.f("ck_sources_type_valid"), "sources", f"type IN {NEW_TYPES}")
    op.drop_constraint(op.f("ck_sources_stored_path_by_hash"), "sources", type_="check")
    op.create_check_constraint(
        op.f("ck_sources_stored_path_by_hash"),
        "sources",
        STORED_PATH.format(types="('pdf', 'docx', 'pptx', 'markdown', 'text')"),
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM sources WHERE type = 'text') THEN
                RAISE EXCEPTION 'sources of type text exist; remove or re-type them first';
            END IF;
        END $$
        """
    )
    op.drop_constraint(op.f("ck_sources_stored_path_by_hash"), "sources", type_="check")
    op.execute("UPDATE sources SET stored_path = NULL WHERE type = 'markdown'")
    op.create_check_constraint(
        op.f("ck_sources_stored_path_by_hash"),
        "sources",
        STORED_PATH.format(types="('pdf', 'docx', 'pptx')"),
    )
    op.drop_constraint(op.f("ck_sources_type_valid"), "sources", type_="check")
    op.create_check_constraint(op.f("ck_sources_type_valid"), "sources", f"type IN {OLD_TYPES}")
