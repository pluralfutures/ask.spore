"""Authentication middleware: Phase 0 bearer token or Authentik OIDC, by configuration.

``[auth] mode`` in ``config/models.toml`` picks one per process (the Instance runs
either): ``phase0`` delegates to ``app.core.phase0_auth`` (eval harness), ``oidc``
validates the Authentik access token (``app.auth.tokens``) from the
``askspore_session`` cookie or an ``Authorization: Bearer`` header, then binds the
request context of the user named by the token's tenant and email
(``app.tenancy.context``). Every failure is the same 401.
"""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.tokens import InvalidToken, TokenValidator
from app.core.logging import log
from app.core.phase0_auth import Phase0AuthMiddleware
from app.tenancy.context import bind, resolve_user

SESSION_COOKIE = "askspore_session"
# Unauthenticated: liveness, the auth mode, and the sign-in link endpoints.
PUBLIC_PATHS = frozenset(
    {
        "/healthz",
        "/api/v1/auth/mode",
        "/api/v1/auth/link",
        "/api/v1/auth/link/complete",
        "/api/v1/auth/logout",
    }
)
# Public in both modes: liveness, and the mode the web app asks before signing in.
ALWAYS_PUBLIC = frozenset({"/healthz", "/api/v1/auth/mode"})
IDENTITY_KEY = "identity"

_UNAUTHORIZED_BODY = json.dumps({"detail": "unauthorized"}).encode()


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return str(value.decode("latin-1"))
    return None


def presented_token(scope: Scope) -> str | None:
    """The bearer token, from the Authorization header or else the session cookie."""
    header = _header(scope, b"authorization")
    if header is not None:
        scheme, _, token = header.partition(" ")
        return token.strip() if scheme.lower() == "bearer" and token.strip() else None
    cookies = cookie_parser(_header(scope, b"cookie") or "")
    return cookies.get(SESSION_COOKIE) or None


class AuthMiddleware:
    """Dispatches to the configured authentication mode."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._phase0 = Phase0AuthMiddleware(app)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in ALWAYS_PUBLIC:
            await self.app(scope, receive, send)
            return
        state: Any = scope["app"].state
        if state.settings.models.auth.mode == "phase0":
            await self._phase0(scope, receive, send)
            return
        if scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        validator: TokenValidator = state.token_validator
        token = presented_token(scope)
        if token is None:
            await reject(send, "no_token")
            return
        try:
            identity = await validator.validate(token)
        except InvalidToken as exc:
            await reject(send, exc.error_code)
            return
        scope.setdefault("state", {})[IDENTITY_KEY] = identity

        context = await resolve_user(state.db_factory, identity.tenant_id, identity.email)
        if context is None:
            await reject(send, "unknown_user")
            return
        bind(scope, context)
        await self.app(scope, receive, send)


async def reject(send: Send, reason: str) -> None:
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
