"""PHASE 0 ONLY authentication. Replaced in Phase 1 by Authentik OIDC.

Do not extend this module; Phase 1 deletes it (design/specs/phase-0-build-spec.md,
P0-06, and "Not in this phase").

Every request except the liveness probe must carry:

- ``Authorization: Bearer <PHASE0_BEARER_TOKEN>``, one token shared by the team and
  read from the environment;
- ``X-User-Email`` naming a user seeded into the single hard-coded ``internal``
  tenant (PHASE0_INTERNAL_USERS at migration time).

The tenant is never taken from the request. On success the middleware sets
``request.state.tenant_id`` and ``request.state.user_id``; ``app.api.deps.db_session``
then scopes each database transaction to that tenant (``app.tenant_id``). Every
failure returns the same 401 so the response does not reveal which check failed or
whether an email exists.
"""

from __future__ import annotations

import hmac
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.db import tenant_session
from app.core.logging import log
from app.tenancy.models import INTERNAL_TENANT_ID, User

# Paths served without authentication. Liveness only; it returns no data.
PUBLIC_PATHS = frozenset({"/healthz"})
MAX_EMAIL_LENGTH = 320

_UNAUTHORIZED_BODY = json.dumps({"detail": "unauthorized"}).encode()


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return str(value.decode("latin-1"))
    return None


def token_matches(header: str | None, expected: str) -> bool:
    """Constant-time check of an ``Authorization: Bearer <token>`` header."""
    if header is None:
        return False
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return False
    return hmac.compare_digest(presented.strip().encode(), expected.encode())


async def lookup_internal_user(
    factory: async_sessionmaker[AsyncSession], email: str
) -> UUID | None:
    """The ID of a seeded user in the internal tenant, looked up under RLS."""
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        user_id: UUID | None = await session.scalar(
            select(User.id).where(
                User.tenant_id == INTERNAL_TENANT_ID, User.email == email.strip().lower()
            )
        )
    return user_id


class Phase0AuthMiddleware:
    """PHASE 0 ONLY. Shared bearer token plus X-User-Email; see module docstring."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        state = scope["app"].state
        expected: str = state.settings.secrets.phase0_bearer_token.get_secret_value()

        if not token_matches(_header(scope, b"authorization"), expected):
            await self._reject(send, "bad_token")
            return

        email = _header(scope, b"x-user-email")
        if not email or len(email) > MAX_EMAIL_LENGTH:
            await self._reject(send, "no_user")
            return

        user_id = await lookup_internal_user(state.db_factory, email)
        if user_id is None:
            await self._reject(send, "unknown_user")
            return

        scope.setdefault("state", {})
        scope["state"]["tenant_id"] = INTERNAL_TENANT_ID
        scope["state"]["user_id"] = user_id
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Send, reason: str) -> None:
        log("auth.rejected", status="401", error_code=reason)
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})
