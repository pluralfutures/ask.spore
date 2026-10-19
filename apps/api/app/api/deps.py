"""Request dependencies shared by routers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import tenant_session
from app.core.logging import log
from app.tenancy.context import STATE_KEY, RequestContext

UNAUTHORIZED = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
FORBIDDEN = HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")


def request_context(request: Request) -> RequestContext:
    """Set by authentication from the credential, never from request parameters.

    A request that reaches a tenant route without one is refused: fail closed, no
    transaction is opened.
    """
    context = getattr(request.state, STATE_KEY, None)
    if not isinstance(context, RequestContext):
        raise UNAUTHORIZED
    return context


def require_tenant_admin(request: Request) -> RequestContext:
    """Tenant admin routes (P1a-13): 401 without a session, 403 for any other role.

    Used as a route dependency, so the refusal comes before the body is validated.
    """
    context = request_context(request)
    if not context.is_tenant_admin:
        log(
            "tenant_admin.refused",
            tenant_id=str(context.tenant_id),
            user_id=str(context.user_id),
            error_code="not_tenant_admin",
        )
        raise FORBIDDEN
    return context


def current_tenant_id(request: Request) -> UUID:
    return request_context(request).tenant_id


def current_user_id(request: Request) -> UUID:
    return request_context(request).user_id


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A transaction scoped to the request's tenant (``app.tenant_id``) for RLS."""
    async with tenant_session(request.app.state.db_factory, current_tenant_id(request)) as session:
        yield session
