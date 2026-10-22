"""The operator dependency (P1a-03): who may use the console, and its transactions.

Operator routes do not use the tenant context for authorisation. ``require_operator``
admits a caller only when all of these hold:

- they signed in with Authentik (an OIDC identity is on the request; the Phase 0
  shared bearer token never reaches the console);
- their request context is a user of the internal (platform) tenant;
- that user is listed in ``operators`` (granted with ``ask-spore operators grant``).

A tenant admin of any client tenant fails the second check. The console's
transactions then run as ``askspore_operator`` (``operator_session``), outside tenant
RLS but without privileges on any chat table.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import request_context
from app.auth.middleware import IDENTITY_KEY
from app.core.db import AUTH_ROLE, OPERATOR_ROLE, role_session
from app.core.logging import log
from app.operator.models import Operator
from app.tenancy.models import INTERNAL_TENANT_ID

FORBIDDEN = HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")


@dataclass(frozen=True)
class OperatorContext:
    user_id: UUID


async def require_operator(request: Request) -> OperatorContext:
    context = request_context(request)  # 401 without authentication
    identity = getattr(request.state, IDENTITY_KEY, None)
    if identity is None:
        log("operator.refused", error_code="not_oidc")
        raise FORBIDDEN
    if identity.service:
        # P1b-15 a: the eval harness's credential never opens the console.
        log("operator.refused", error_code="service_identity")
        raise FORBIDDEN
    if context.tenant_id != INTERNAL_TENANT_ID:
        log("operator.refused", tenant_id=str(context.tenant_id), error_code="not_platform")
        raise FORBIDDEN
    async with role_session(request.app.state.db_factory, AUTH_ROLE) as session:
        listed = await session.scalar(
            select(Operator.user_id).where(
                Operator.tenant_id == INTERNAL_TENANT_ID, Operator.user_id == context.user_id
            )
        )
    if listed is None:
        log("operator.refused", user_id=str(context.user_id), error_code="not_operator")
        raise FORBIDDEN
    return OperatorContext(user_id=context.user_id)


async def operator_session(
    request: Request, _: OperatorContext = Depends(require_operator)
) -> AsyncIterator[AsyncSession]:
    """A transaction as ``askspore_operator``; only after ``require_operator`` passed."""
    async with role_session(request.app.state.db_factory, OPERATOR_ROLE) as session:
        yield session
