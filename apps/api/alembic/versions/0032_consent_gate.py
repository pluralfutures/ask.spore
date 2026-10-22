"""P1b-10: the first-login consent gate.

``users`` (tenant-scoped, RLS and the ``tenant_id``-first keys unchanged since revision
0001) gains:

- ``consent_version`` and ``consented_at``: the use and privacy notice version the user
  last accepted (``config/consent/<version>.md``) and when. Both null until the first
  acceptance, both set together after it. A user whose version is not the active one
  (``[consent] version`` in ``config/models.toml``) is refused every conversation, file
  and tenant admin route until they accept it.
- ``consent_notice_version``: the active version for which the ``consent_notice`` email
  was queued, so a version change sends one email per user (the worker's tick).

The application role may update the three columns only (column grants, as in 0005).

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-22 14:00:00
"""

from collections.abc import Sequence

from alembic import op

APP_ROLE = "askspore_app"
COLUMNS = "consent_version, consented_at, consent_notice_version"
VERSION = "'^v[1-9][0-9]*$'"

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN consent_version text, "
        "ADD COLUMN consented_at timestamptz, "
        "ADD COLUMN consent_notice_version text"
    )
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_consent_recorded "
        "CHECK ((consent_version IS NULL) = (consented_at IS NULL))"
    )
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_consent_version_format "
        f"CHECK (consent_version ~ {VERSION} AND consent_notice_version ~ {VERSION})"
    )
    op.execute(f"GRANT UPDATE ({COLUMNS}) ON users TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE ({COLUMNS}) ON users FROM {APP_ROLE}")
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_consent_version_format")
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_consent_recorded")
    op.execute(
        "ALTER TABLE users DROP COLUMN consent_notice_version, "
        "DROP COLUMN consented_at, DROP COLUMN consent_version"
    )
