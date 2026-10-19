"""Granting and revoking the operator role (P1a-03), from the command line only.

The API has no route that makes anyone an operator: ``ask-spore operators grant``
runs as the schema owner (MIGRATIONS_DATABASE_URL), like a migration. An operator is
a user of the internal (platform) tenant; ``grant`` creates that user if needed, and
in ``[auth] mode = "oidc"`` provisions them in Authentik so they can sign in with a
link. Both commands write an audit event under the internal tenant.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.auth.provider import SignInLinkProvider
from app.core.db import tenant_session
from app.operator.models import Operator
from app.tenancy.models import INTERNAL_TENANT_ID, User

GrantResult = Literal["granted", "already_operator", "no_user"]
RevokeResult = Literal["revoked", "not_operator"]


async def grant_operator(
    owner_factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
    display_name: str | None,
    provider: SignInLinkProvider | None,
) -> GrantResult:
    email = email.strip().lower()
    async with tenant_session(owner_factory, INTERNAL_TENANT_ID) as session:
        user = await session.scalar(
            select(User).where(User.tenant_id == INTERNAL_TENANT_ID, User.email == email)
        )
        if user is None:
            if not display_name:
                return "no_user"
            user = User(
                id=uuid.uuid4(),
                tenant_id=INTERNAL_TENANT_ID,
                email=email,
                display_name=display_name,
                status="invited",
            )
            session.add(user)
            await session.flush()
        if provider is not None:
            await provider.provision_user(
                email=email, display_name=user.display_name, tenant_id=INTERNAL_TENANT_ID
            )
        added = await session.scalar(
            insert(Operator)
            .values(tenant_id=INTERNAL_TENANT_ID, user_id=user.id)
            .on_conflict_do_nothing()
            .returning(Operator.user_id)
        )
        if added is None:
            return "already_operator"
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=None,
            event="operator.granted",
            metadata={"before": {}, "after": {"user_id": str(user.id), "role": "operator"}},
        )
    return "granted"


async def revoke_operator(
    owner_factory: async_sessionmaker[AsyncSession], *, email: str
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
                delete(Operator)
                .where(Operator.tenant_id == INTERNAL_TENANT_ID, Operator.user_id == user_id)
                .returning(Operator.user_id)
            )
        if removed is None:
            return "not_operator"
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=None,
            event="operator.revoked",
            metadata={"before": {"user_id": str(removed), "role": "operator"}, "after": {}},
        )
    return "revoked"
