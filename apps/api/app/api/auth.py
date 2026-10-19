"""/api/v1/auth: sign-in links (P1a-02). Public routes; see ``app.auth.links``.

``POST /auth/link`` sets the browser-binding cookie and answers 202 the same way for
every address; the lookup and the email run after the response. ``POST
/auth/link/complete`` is the only route that submits a link token, and only the
landing page's button calls it: there is no GET that consumes anything. On success
the Authentik access token is set as the ``askspore_session`` cookie (HttpOnly,
Secure, SameSite=Strict) and never returned in a body.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status

from app.api.schemas import AuthModeOut, LinkCompleteIn, LinkRequestIn, LinkRequestOut
from app.auth.links import SignInRefused, complete_link, new_binding, request_link
from app.auth.middleware import SESSION_COOKIE

router = APIRouter(prefix="/api/v1/auth")

BINDING_COOKIE = "askspore_link_binding"
# The binding cookie is sent only to the completion route, never to anything else.
BINDING_PATH = "/api/v1/auth/link"


def _require_oidc(request: Request) -> Any:
    settings = request.app.state.settings
    if settings.models.auth.mode != "oidc":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
    return settings


def _cookie(response: Response, name: str, value: str, *, max_age: int, path: str) -> None:
    response.set_cookie(
        name, value, max_age=max_age, path=path, secure=True, httponly=True, samesite="strict"
    )


@router.get("/mode", response_model=AuthModeOut)
async def auth_mode(request: Request) -> AuthModeOut:
    return AuthModeOut(mode=request.app.state.settings.models.auth.mode)


@router.post("/link", status_code=status.HTTP_202_ACCEPTED, response_model=LinkRequestOut)
async def request_sign_in_link(
    body: LinkRequestIn, request: Request, response: Response, background: BackgroundTasks
) -> LinkRequestOut:
    settings = _require_oidc(request)
    binding = new_binding()
    ttl = settings.models.auth.link_ttl_seconds
    _cookie(response, BINDING_COOKIE, binding, max_age=ttl, path=BINDING_PATH)
    background.add_task(
        request_link,
        factory=request.app.state.db_factory,
        provider=request.app.state.sign_in_provider,
        config=settings.models.auth,
        email=body.email,
        binding=binding,
    )
    return LinkRequestOut(status="sent_if_known")


@router.post("/link/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_sign_in_link(body: LinkCompleteIn, request: Request) -> Response:
    _require_oidc(request)
    try:
        signed_in = await complete_link(
            factory=request.app.state.db_factory,
            provider=request.app.state.sign_in_provider,
            validator=request.app.state.token_validator,
            token=body.token,
            binding=request.cookies.get(BINDING_COOKIE),
        )
    except SignInRefused:
        refused = Response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=b'{"detail":"sign_in_failed"}',
            media_type="application/json",
        )
        refused.delete_cookie(BINDING_COOKIE, path=BINDING_PATH)
        return refused
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    lifetime = int((signed_in.expires_at - datetime.now(UTC)).total_seconds())
    _cookie(response, SESSION_COOKIE, signed_in.access_token, max_age=max(lifetime, 0), path="/")
    response.delete_cookie(BINDING_COOKIE, path=BINDING_PATH)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return response
