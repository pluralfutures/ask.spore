"""The request's tenant context, resolved from the authenticated user (P1a-01).

Authentication (Phase 0 bearer token or Authentik OIDC, ``app.auth``) establishes
who the caller is; ``resolve_user`` then finds the caller's ``users`` row *inside*
the tenant the credential names, under that tenant's row-level-security scope, and
yields a ``RequestContext``. The tenant ID never comes from request parameters.
``app.api.deps`` reads the context and scopes every transaction to its tenant
(``app.tenant_id``); a request without one is refused (fail closed).
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import RevokedSession
from app.core.db import tenant_session
from app.tenancy.models import Tenant, User

STATE_KEY = "auth_context"


@dataclass(frozen=True)
class RequestContext:
    tenant_id: UUID
    user_id: UUID
    role: str  # users.role: "user" or "tenant_admin"
    status: str = "active"  # users.status before this sign-in ("invited" on the first one)

    @property
    def is_tenant_admin(self) -> bool:
        return self.role == "tenant_admin"


def bind(scope: MutableMapping[str, Any], context: RequestContext) -> None:
    """Attach ``context`` to an ASGI scope (read back by ``app.api.deps``)."""
    state = scope.setdefault("state", {})
    state[STATE_KEY] = context
    state["tenant_id"] = context.tenant_id
    state["user_id"] = context.user_id


async def resolve_user(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    email: str,
    *,
    allow_invited: bool = False,
    token_sha256: str | None = None,
) -> RequestContext | None:
    """The active user ``email`` of the active tenant ``tenant_id``, or None.

    Runs in a transaction scoped to ``tenant_id``, so a row of any other tenant is
    invisible even if the email matches. ``allow_invited`` admits a user whose first
    sign-in this is (P1a-02); every other caller needs ``status = 'active'``.
    ``token_sha256``: the hash of the presented access token; a token revoked by
    sign-out (``revoked_sessions``) resolves to None (P1a-02).
    """
    statuses = ("active", "invited") if allow_invited else ("active",)
    query = (
        select(User.id, User.role, User.status)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(
            User.tenant_id == tenant_id,
            User.email == email.strip().lower(),
            User.status.in_(statuses),
            Tenant.status == "active",
        )
    )
    if token_sha256 is not None:
        query = query.where(
            ~exists().where(
                RevokedSession.tenant_id == tenant_id,
                RevokedSession.token_sha256 == token_sha256,
            )
        )
    async with tenant_session(factory, tenant_id) as session:
        row = (await session.execute(query)).one_or_none()
    if row is None:
        return None
    return RequestContext(tenant_id=tenant_id, user_id=row.id, role=row.role, status=row.status)
