"""P1c-09: the cut-off and partial flags on assistant messages.

- ``messages.truncated``: the answer stopped at the output budget (finish reason
  ``length``, Phase 1a release F4). Stored so the cut-off note survives a reload and shows
  in the history; until now only the stream's ``done`` event carried it.
- ``messages.partial``: the answer ended early, because the user pressed "stop", the
  client left or the model failed mid-stream. The stored text is what the user had been
  shown (nothing, for a corpus-only answer still held back before its first citation).

Both default to false, so every existing row reads as complete. Only an assistant
message may carry either flag.

Revision ID: 0050
Revises: 0041
Create Date: 2026-10-23 12:00:00

Numbered from 0050 on 0041 because Group A adds 0042 in parallel; the integration step
re-parents this revision (one ``down_revision`` line).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ("truncated", "partial"):
        op.add_column(
            "messages",
            sa.Column(column, sa.Boolean(), server_default=sa.text("false"), nullable=False),
        )
    op.create_check_constraint(
        op.f("ck_messages_flags_assistant_only"),
        "messages",
        "role = 'assistant' OR (NOT truncated AND NOT partial)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_messages_flags_assistant_only"), "messages", type_="check")
    op.drop_column("messages", "partial")
    op.drop_column("messages", "truncated")
