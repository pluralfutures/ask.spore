"""P1b-03 adjustments (owner decision 5 of Oct 22, 2026): licence-ground takedowns.

- ``sources.takedown_licence_grounds``: the takedown request is on licence grounds
  (the publisher says we may not use the text; a licence breach we find ourselves is
  always one). Only a row with a takedown request may carry it.
- When such a source is withdrawn, the excerpts stored in users' history are the
  licensed text: the withdrawal job blanks them (``excerpt = ''``), keeping the
  citation, its provenance and the "withdrawn" label. Other withdrawals keep the
  excerpt.
- ``askspore_content`` (revision 0015) may therefore update ``citations.excerpt``, but a
  trigger lets that role write only the empty string: it can blank an excerpt, never
  write text into one. It still cannot read the excerpt.

Chained on 0022 (Group B, phase-1b/group-b-integration). Group A2 numbers its
revisions from 0023.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-22 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

CONTENT_ROLE = "askspore_content"

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "takedown_licence_grounds",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_sources_licence_grounds_need_takedown"),
        "sources",
        "NOT takedown_licence_grounds OR takedown_requested_on IS NOT NULL",
    )

    op.execute(f"GRANT UPDATE (excerpt) ON citations TO {CONTENT_ROLE}")
    op.execute(
        f"""
        CREATE FUNCTION citations_content_blank_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_user = '{CONTENT_ROLE}'
               AND NEW.excerpt IS DISTINCT FROM OLD.excerpt
               AND NEW.excerpt <> '' THEN
                RAISE EXCEPTION '{CONTENT_ROLE} may only blank a citation excerpt';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER citations_content_blank_only BEFORE UPDATE OF excerpt ON citations "
        "FOR EACH ROW EXECUTE FUNCTION citations_content_blank_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER citations_content_blank_only ON citations")
    op.execute("DROP FUNCTION citations_content_blank_only()")
    op.execute(f"REVOKE UPDATE (excerpt) ON citations FROM {CONTENT_ROLE}")
    op.drop_constraint(op.f("ck_sources_licence_grounds_need_takedown"), "sources", type_="check")
    op.drop_column("sources", "takedown_licence_grounds")
