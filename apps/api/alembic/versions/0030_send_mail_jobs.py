"""P1b-11: ``send_mail`` jobs on the P1b-02 queue.

Platform mail is sent by the worker, from ``jobs`` rows of a new type ``send_mail``.
Like every job, its payload carries identifiers only, never an address, subject or
body: the worker reads the recipient's address and renders the template at send time.

- ``type`` gains ``send_mail``.
- The payload's allowed keys gain ``template`` (a template name), ``tenant_id``,
  ``user_id`` (the recipient) and ``notice_id`` (the operator notice that caused it);
  ``template`` is a short identifier, and a ``send_mail`` job must name one.
- The one-active-job-per-subject index covers the new keys too, so a second invitation
  for the same user while one is queued is the same job, and two notices are two jobs.
- ``askspore_operator`` may read and add jobs: the operator console's first-admin
  invite enqueues its invitation in the invite's own transaction. It may not update
  them; the worker (the application role) runs them.

No table is added; ``jobs`` stays operator-owned and shared, outside tenant RLS.

Revision ID: 0030
Revises: 0022
Create Date: 2026-10-22 10:00:00

Numbered from 0030 on 0022 because Group A2 adds 0023 onwards in parallel; the
integration step re-parents this revision onto Group A2's last one.
"""

from collections.abc import Sequence

from alembic import op

OPERATOR_ROLE = "askspore_operator"
OLD_TYPES = "('ingest_source', 'withdraw_source', 'crawl_site')"
NEW_TYPES = "('ingest_source', 'withdraw_source', 'crawl_site', 'send_mail')"
OLD_KEYS = "ARRAY['source_id', 'site_id', 'add_tags', 'downloadable', 'parse_timeout']"
NEW_KEYS = (
    "ARRAY['source_id', 'site_id', 'add_tags', 'downloadable', 'parse_timeout', "
    "'template', 'tenant_id', 'user_id', 'notice_id']"
)
OLD_SUBJECT = (
    "(type, (payload->>'source_id'), (payload->>'site_id'), "
    "(coalesce(payload->'add_tags', '[]'::jsonb)))"
)
NEW_SUBJECT = (
    "(type, (payload->>'source_id'), (payload->>'site_id'), "
    "(coalesce(payload->'add_tags', '[]'::jsonb)), (payload->>'template'), "
    "(payload->>'tenant_id'), (payload->>'user_id'), (payload->>'notice_id'))"
)

revision: str = "0030"
down_revision: str | None = "0022"
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


def upgrade() -> None:
    op.drop_constraint(op.f("ck_jobs_type_valid"), "jobs", type_="check")
    op.create_check_constraint(op.f("ck_jobs_type_valid"), "jobs", f"type IN {NEW_TYPES}")
    op.drop_constraint(op.f("ck_jobs_payload_identifiers_only"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_payload_identifiers_only"), "jobs", _payload_check(NEW_KEYS)
    )
    op.create_check_constraint(
        op.f("ck_jobs_mail_template"),
        "jobs",
        "(type <> 'send_mail' OR payload ? 'template') AND "
        "(NOT payload ? 'template' OR payload->>'template' ~ '^[a-z0-9_]{1,64}$')",
    )
    _subject_index(NEW_SUBJECT)
    op.execute(f"GRANT SELECT, INSERT ON jobs TO {OPERATOR_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT, INSERT ON jobs FROM {OPERATOR_ROLE}")
    op.execute("DELETE FROM jobs WHERE type = 'send_mail'")
    _subject_index(OLD_SUBJECT)
    op.drop_constraint(op.f("ck_jobs_mail_template"), "jobs", type_="check")
    op.drop_constraint(op.f("ck_jobs_payload_identifiers_only"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_payload_identifiers_only"), "jobs", _payload_check(OLD_KEYS)
    )
    op.drop_constraint(op.f("ck_jobs_type_valid"), "jobs", type_="check")
    op.create_check_constraint(op.f("ck_jobs_type_valid"), "jobs", f"type IN {OLD_TYPES}")
