"""The consent gate on conversation, file and tenant admin routes (P1b-10).

A signed-in user whose accepted notice version is not the active one
(``[consent] version``) is refused with 403 ``consent_required``, before the request
body is read or a transaction opened. The gate is a router dependency, so a route added
to a gated router later is gated too (fail closed); only the routes in ``EXEMPT_ROUTES``
(health and the signed-in user's own details) are not. The consent routes
(``app.api.consent``), the operator and content consoles (``/api/v1/operator``,
``/api/v1/content``: internal tenant staff) and the sign-in routes are separate routers
and are not gated.

The eval harness's service identity (P1b-15 a, ``Identity.service``) is not gated either:
it is not a natural person, so there is no one to show the notice to. It exists only on
the internal tenant and only when ``[auth.eval_service]`` is configured, which the
production config is not. Every human user of the internal tenant stays gated.
"""

from __future__ import annotations

from typing import Final

from fastapi import HTTPException, Request, status

from app.api.deps import request_context
from app.auth.middleware import IDENTITY_KEY
from app.auth.tokens import Identity
from app.core.config import Settings
from app.core.logging import log

CONSENT_REQUIRED = HTTPException(status.HTTP_403_FORBIDDEN, detail="consent_required")
EXEMPT_ROUTES: Final[frozenset[str]] = frozenset({"/api/v1/healthz", "/api/v1/me"})


def active_version(request: Request) -> str:
    settings: Settings = request.app.state.settings
    return settings.models.consent.version


def require_consent(request: Request) -> None:
    route = getattr(request.scope.get("route"), "path", None)
    if route in EXEMPT_ROUTES:
        return
    identity: Identity | None = getattr(request.state, IDENTITY_KEY, None)
    if identity is not None and identity.service:
        return
    context = request_context(request)
    if context.consent_version != active_version(request):
        log(
            "consent.refused",
            tenant_id=str(context.tenant_id),
            user_id=str(context.user_id),
            error_code="consent_required",
        )
        raise CONSENT_REQUIRED
