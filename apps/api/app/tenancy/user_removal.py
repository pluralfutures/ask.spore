"""Removing one user (P1c-07): their account data and history, deleted.

The tenant admin's ``DELETE /api/v1/admin/users/{id}`` and the operator's
``DELETE /api/v1/operator/tenants/{tenant}/users/{id}`` call ``remove_user`` inside their
own transaction, after their own access checks. It switches to ``askspore_user_removal``
(revision 0051) with ``app.tenant_id`` set to the user's tenant, so the tenant tables'
RLS policies bound every statement to that tenant, and

- refuses (``RemovalRefused``, nothing deleted) the caller themselves, a tenant's last
  admin who is not deactivated, an internal-tenant user holding an operator or content
  role, and a user named as proposer or approver in the source or site register (the
  register's provenance stays);
- deletes, as the termination purge does for a whole tenant (``app.tenancy.termination``,
  same table order, children first): the user's conversations with their messages,
  citations and feedback, the user's feedback on any message, their download records,
  revoked sessions, sign-in links and MFA challenges, the jobs whose payload names them
  (their invitation or consent-notice mail), and the ``users`` row;
- clears the user as author of workspace prompt versions (the versions stay, they are
  the workspace's) and as creator of jobs;
- keeps what termination keeps: the audit events (append-only; they keep the user's ID
  as actor) and the usage ledger, which has no user column.

Before deleting anything it checks that it knows every column that names a user
(``user_id``, ``*_user_id``, ``created_by``, ``proposed_by``, ``approved_by``), so a
table added later cannot keep a removed user's rows silently.

The user's Authentik account is disabled by the route (the provisioner may change a user
but not delete one); deleting it is a manual step in Authentik's admin interface, as for
a terminated tenant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import APP_ROLE, OPERATOR_ROLE, USER_REMOVAL_ROLE, set_tenant
from app.tenancy.models import INTERNAL_TENANT_ID
from app.tenancy.termination import PURGED_TABLES

# Every (table, column) that names a user, and what removal does with it.
DELETED_BY_COLUMN: Final = {
    "conversations": "user_id",
    "feedback": "user_id",
    "downloads": "user_id",
    "revoked_sessions": "user_id",
    "sign_in_links": "user_id",
    "mfa_challenges": "user_id",
}
CLEARED_COLUMNS: Final = (("workspace_prompts", "author_user_id"), ("jobs", "created_by"))
KEPT_COLUMNS: Final = (("audit_events", "actor_user_id"),)
REFUSING_COLUMNS: Final = (
    ("operators", "user_id"),
    ("content_roles", "user_id"),
    ("sources", "proposed_by"),
    ("sources", "approved_by"),
    ("sites", "proposed_by"),
    ("sites", "approved_by"),
)
KNOWN_USER_COLUMNS: Final = frozenset(
    {(table, column) for table, column in DELETED_BY_COLUMN.items()}
    | set(CLEARED_COLUMNS)
    | set(KEPT_COLUMNS)
    | set(REFUSING_COLUMNS)
)
# Rows deleted through the user's conversations, in termination's order (children first).
REMOVED_TABLES: Final = tuple(
    t for t in PURGED_TABLES if t in {*DELETED_BY_COLUMN, "messages", "citations", "users"}
)
_RESTORABLE: Final = frozenset({APP_ROLE, OPERATOR_ROLE})


class RemovalRefused(Exception):
    """The user was not removed; ``code`` says why. Nothing was deleted."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RemovedUser:
    user_id: uuid.UUID
    email: str
    role: str
    status: str
    counts: dict[str, int]  # rows deleted per table, plus jobs and cleared references

    @property
    def total(self) -> int:
        return sum(self.counts.values())


async def unknown_user_columns(session: AsyncSession) -> set[tuple[str, str]]:
    """Columns naming a user that this module does not know. From ``pg_catalog``, which
    every role reads (``information_schema`` lists only the caller's own tables)."""
    rows = await session.execute(
        text(
            "SELECT c.relname, a.attname FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND a.attnum > 0 "
            "AND NOT a.attisdropped AND (a.attname = 'user_id' "
            "OR a.attname LIKE '%\\_user\\_id' "
            "OR a.attname IN ('created_by', 'proposed_by', 'approved_by'))"
        )
    )
    return {(str(r[0]), str(r[1])) for r in rows} - KNOWN_USER_COLUMNS


async def remove_user(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    restore_role: str,
) -> RemovedUser:
    """Delete ``user_id`` of ``tenant_id`` in the caller's transaction (see the module).

    ``restore_role`` is the role the caller's transaction runs as (``askspore_app`` for a
    tenant admin, ``askspore_operator`` for the operator); it is restored afterwards, with
    ``app.tenant_id`` left on the user's tenant for the caller's audit event.
    """
    if restore_role not in _RESTORABLE:
        raise ValueError(f"not a role to restore: {restore_role}")
    if user_id == actor_user_id:
        raise RemovalRefused("cannot_remove_self")
    await set_tenant(session, tenant_id)
    found = (
        await session.execute(
            text("SELECT email, role, status FROM users WHERE id = :u AND tenant_id = :t"),
            {"u": user_id, "t": tenant_id},
        )
    ).one_or_none()
    if found is None:
        raise RemovalRefused("not_found")
    email, role, status = str(found.email), str(found.role), str(found.status)

    await session.execute(text(f"SET LOCAL ROLE {USER_REMOVAL_ROLE}"))
    await set_tenant(session, tenant_id)
    if await unknown_user_columns(session):
        raise RemovalRefused("unknown_user_table")
    params = {"u": user_id, "t": tenant_id}
    if role == "tenant_admin":
        others = await session.scalar(
            text(
                "SELECT count(*) FROM users WHERE tenant_id = :t AND id <> :u "
                "AND role = 'tenant_admin' AND status <> 'deactivated'"
            ),
            params,
        )
        if not others:
            raise RemovalRefused("last_admin")
    if tenant_id == INTERNAL_TENANT_ID:
        for table in ("operators", "content_roles"):
            if await session.scalar(
                text(f"SELECT 1 FROM {table} WHERE user_id = :u LIMIT 1"),  # noqa: S608
                params,
            ):
                raise RemovalRefused("platform_role")
    for table in ("sources", "sites"):
        if await session.scalar(
            text(
                f"SELECT 1 FROM {table} WHERE proposed_by = :u OR approved_by = :u LIMIT 1"  # noqa: S608
            ),
            params,
        ):
            raise RemovalRefused("register_author")

    counts: dict[str, int] = {}
    conversations = "SELECT id FROM conversations WHERE user_id = :u"
    messages = f"SELECT id FROM messages WHERE conversation_id IN ({conversations})"  # noqa: S608
    where = {
        "feedback": f"user_id = :u OR message_id IN ({messages})",
        "citations": f"message_id IN ({messages})",
        "messages": f"conversation_id IN ({conversations})",
        "users": "id = :u",
        **{t: f"{c} = :u" for t, c in DELETED_BY_COLUMN.items() if t != "feedback"},
    }
    for table in REMOVED_TABLES:
        result = await session.execute(
            text(f"DELETE FROM {table} WHERE tenant_id = :t AND ({where[table]})"),  # noqa: S608
            params,
        )
        counts[table] = int(getattr(result, "rowcount", 0) or 0)
        if table == "mfa_challenges":
            # The references that stay without the user, before the users row goes.
            cleared = await session.execute(
                text(
                    "UPDATE workspace_prompts SET author_user_id = NULL "
                    "WHERE tenant_id = :t AND author_user_id = :u"
                ),
                params,
            )
            counts["workspace_prompts_cleared"] = int(getattr(cleared, "rowcount", 0) or 0)
    jobs = await session.execute(
        text("DELETE FROM jobs WHERE payload->>'tenant_id' = :ts AND payload->>'user_id' = :us"),
        {"ts": str(tenant_id), "us": str(user_id)},
    )
    counts["jobs"] = int(getattr(jobs, "rowcount", 0) or 0)
    created = await session.execute(
        text(
            "UPDATE jobs SET created_by = NULL "
            "WHERE created_by = :u AND payload->>'tenant_id' = :ts"
        ),
        {"u": user_id, "ts": str(tenant_id)},
    )
    counts["jobs_cleared"] = int(getattr(created, "rowcount", 0) or 0)

    await session.execute(text(f"SET LOCAL ROLE {restore_role}"))
    await set_tenant(session, tenant_id)
    return RemovedUser(user_id, email, role, status, counts)
