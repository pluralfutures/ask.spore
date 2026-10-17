"""Request dependencies shared by routers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import tenant_session


def current_tenant_id(request: Request) -> UUID:
    """Set by the auth middleware from the credential, never from request parameters."""
    tenant_id: UUID = request.state.tenant_id
    return tenant_id


def current_user_id(request: Request) -> UUID:
    user_id: UUID = request.state.user_id
    return user_id


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A transaction scoped to the request's tenant (``app.tenant_id``) for RLS."""
    async with tenant_session(request.app.state.db_factory, current_tenant_id(request)) as session:
        yield session
