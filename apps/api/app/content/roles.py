"""Content roles (P1b-01): who may propose and who may review corpus sources.

Two roles, held by users of the internal (platform) tenant in ``content_roles``:

- ``content_editor``: propose sources (files, URLs, sites);
- ``content_reviewer``: approve, reject, retry and withdraw them.

The same person may hold both. Owner decision, Oct 21, 2026: while there is one
internal user, a reviewer may approve their own proposal; ``app.content.register``
audits such an approval with both roles named (backlog: the no-self-approval rule
returns with a second internal user).

Roles are granted and revoked with ``ask-spore content-roles`` as the schema owner,
never through the API, like the operator role. Both write an audit event under the
internal tenant.
"""

from __future__ import annotations

from typing import Final, Literal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.content.models import CONTENT_ROLES, ContentRole
from app.core.db import tenant_session
from app.tenancy.models import INTERNAL_TENANT_ID, User

EDITOR: Final = "content_editor"
REVIEWER: Final = "content_reviewer"

GrantResult = Literal["granted", "already_granted", "no_user"]
RevokeResult = Literal["revoked", "not_granted"]


class RoleError(PermissionError):
    """The acting user lacks a content role, or is not an internal user. ``code`` is safe
    to log."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def roles_of(session: AsyncSession, user_id: UUID) -> frozenset[str]:
    """The content roles of ``user_id``; the session must be scoped to the internal tenant."""
    rows = await session.scalars(
        select(ContentRole.role).where(
            ContentRole.tenant_id == INTERNAL_TENANT_ID, ContentRole.user_id == user_id
        )
    )
    return frozenset(rows.all())


async def require(session: AsyncSession, user_id: UUID, role: str) -> frozenset[str]:
    """The user's roles, or RoleError when ``role`` is not among them."""
    roles = await roles_of(session, user_id)
    if role not in roles:
        raise RoleError(f"not_{role}")
    return roles


async def user_by_email(factory: async_sessionmaker[AsyncSession], email: str) -> UUID:
    """The internal user with ``email``; RoleError("no_user") when there is none."""
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        user_id = await session.scalar(
            select(User.id).where(
                User.tenant_id == INTERNAL_TENANT_ID, User.email == email.strip().lower()
            )
        )
    if user_id is None:
        raise RoleError("no_user")
    return user_id


async def grant_role(
    owner_factory: async_sessionmaker[AsyncSession], *, email: str, role: str
) -> GrantResult:
    if role not in CONTENT_ROLES:
        raise ValueError(f"not a content role: {role}")
    async with tenant_session(owner_factory, INTERNAL_TENANT_ID) as session:
        user_id = await session.scalar(
            select(User.id).where(
                User.tenant_id == INTERNAL_TENANT_ID, User.email == email.strip().lower()
            )
        )
        if user_id is None:
            return "no_user"
        added = await session.scalar(
            insert(ContentRole)
            .values(tenant_id=INTERNAL_TENANT_ID, user_id=user_id, role=role)
            .on_conflict_do_nothing()
            .returning(ContentRole.user_id)
        )
        if added is None:
            return "already_granted"
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=None,
            event="content_role.granted",
            metadata={"before": {}, "after": {"user_id": str(user_id), "role": role}},
        )
    return "granted"


async def revoke_role(
    owner_factory: async_sessionmaker[AsyncSession], *, email: str, role: str
) -> RevokeResult:
    async with tenant_session(owner_factory, INTERNAL_TENANT_ID) as session:
        user_id = await session.scalar(
            select(User.id).where(
                User.tenant_id == INTERNAL_TENANT_ID, User.email == email.strip().lower()
            )
        )
        removed = None
        if user_id is not None:
            removed = await session.scalar(
                delete(ContentRole)
                .where(
                    ContentRole.tenant_id == INTERNAL_TENANT_ID,
                    ContentRole.user_id == user_id,
                    ContentRole.role == role,
                )
                .returning(ContentRole.user_id)
            )
        if removed is None:
            return "not_granted"
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=None,
            event="content_role.revoked",
            metadata={"before": {"user_id": str(removed), "role": role}, "after": {}},
        )
    return "revoked"
