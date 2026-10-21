"""/api/v1/auth: tenant discovery (P1b-06), sign-in links (P1a-02) and SSO through the
tenant's source (P1b-07). Public routes; see ``app.tenancy.login_policy``,
``app.auth.links`` and ``app.auth.sso``.

``POST /auth/link`` sets the browser-binding cookie and answers 202 the same way for
every address; the lookup and the email run after the response. ``POST
/auth/link/complete`` is the only route that submits a link token, and only the
landing page's button calls it: there is no GET that consumes anything. On success
the Authentik access token is set as the ``askspore_session`` cookie (HttpOnly,
Secure, SameSite=Strict) and never returned in a body. ``POST /auth/logout`` clears
the cookie and revokes the token (``app.auth.sessions``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import parse_qsl

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.schemas import (
    AuthModeOut,
    DiscoverIn,
    DiscoverOut,
    LinkCompleteIn,
    LinkRequestIn,
    LinkRequestOut,
    SsoStartOut,
)
from app.auth import sso
from app.auth.links import SignInRefused, complete_link, new_binding, request_link
from app.auth.middleware import SESSION_COOKIE, presented_token
from app.auth.provider import ProviderError
from app.auth.sessions import revoke
from app.core.logging import log
from app.tenancy.login_policy import discover

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


@router.post("/discover", response_model=DiscoverOut)
async def discover_methods(body: DiscoverIn, request: Request) -> DiscoverOut:
    """Tenant discovery (P1b-06): the methods the address's domain allows. Domain-level
    only, so it says nothing about whether the address belongs to a user; an unknown
    domain gets the links-only answer, like any domain without SSO."""
    _require_oidc(request)
    methods, kind = (await discover(request.app.state.db_factory, body.email)).public()
    return DiscoverOut(methods=list(methods), sso_kind=kind)


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


# --- SSO through the tenant's source (P1b-07) ---------------------------------------------

SSO_BINDING_COOKIE = "askspore_sso_binding"
SSO_STATE_COOKIE = "askspore_sso_state"
# The browser sees the IdP's callback under Authentik's paths on our host (Caddy hands
# them to the routes below), so the cookies are scoped to those paths only.
SSO_COOKIE_PATH = "/source/"
SSO_COOKIE_SECONDS = int(sso.ATTEMPT_TTL.total_seconds())
MAX_CALLBACK_PARAMS = 20
MAX_CALLBACK_VALUE = 4096
MAX_SAML_BODY = 512 * 1024
SSO_FAILED_REDIRECT = "/?sign_in=failed"


@router.post("/sso/start", response_model=SsoStartOut)
async def start_sso(body: DiscoverIn, request: Request, response: Response) -> SsoStartOut:
    """Start a sign-in through the address's tenant's source. An unknown domain and a
    domain without SSO get the same 409: discovery already tells the page which."""
    _require_oidc(request)
    try:
        started = await sso.start(
            factory=request.app.state.db_factory,
            provider=request.app.state.sign_in_provider,
            email=body.email,
        )
    except ProviderError as exc:
        log("auth.sso_not_started", level="error", error_code=exc.error_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="sso_unavailable") from None
    if started is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="sso_unavailable")
    # A SAML IdP answers with a cross-site POST, which only SameSite=None cookies follow;
    # an OIDC IdP with a top-level GET, which Lax cookies follow.
    same_site: Literal["lax", "none"] = "none" if started.callback == "saml" else "lax"
    for name, value in ((SSO_BINDING_COOKIE, started.binding), (SSO_STATE_COOKIE, started.resume)):
        response.set_cookie(
            name,
            value,
            max_age=SSO_COOKIE_SECONDS,
            path=SSO_COOKIE_PATH,
            secure=True,
            httponly=True,
            samesite=same_site,
        )
    return SsoStartOut(redirect_url=started.redirect_url)


async def _finish_sso(
    request: Request, callback: sso.CallbackKind, slug: str, params: dict[str, str]
) -> Response:
    _require_oidc(request)
    try:
        signed_in = await sso.complete(
            factory=request.app.state.db_factory,
            provider=request.app.state.sign_in_provider,
            validator=request.app.state.token_validator,
            callback=callback,
            slug=slug,
            params=params,
            binding=request.cookies.get(SSO_BINDING_COOKIE),
            resume=request.cookies.get(SSO_STATE_COOKIE),
        )
        response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        lifetime = int((signed_in.expires_at - datetime.now(UTC)).total_seconds())
        _cookie(
            response, SESSION_COOKIE, signed_in.access_token, max_age=max(lifetime, 0), path="/"
        )
    except SignInRefused:
        response = RedirectResponse(SSO_FAILED_REDIRECT, status_code=status.HTTP_303_SEE_OTHER)
    for name in (SSO_BINDING_COOKIE, SSO_STATE_COOKIE):
        response.delete_cookie(name, path=SSO_COOKIE_PATH, secure=True, httponly=True)
    return response


def _bounded(pairs: list[tuple[str, str]], max_value: int) -> dict[str, str] | None:
    if len(pairs) > MAX_CALLBACK_PARAMS or any(len(v) > max_value for _, v in pairs):
        return None
    return dict(pairs)


@router.get("/sso/oauth/{slug}", include_in_schema=False)
async def sso_oauth_callback(slug: str, request: Request) -> Response:
    """The OIDC IdP's redirect, from ``/source/oauth/callback/<slug>/`` (Caddy)."""
    params = _bounded(list(request.query_params.multi_items()), MAX_CALLBACK_VALUE)
    if params is None:
        return RedirectResponse(SSO_FAILED_REDIRECT, status_code=status.HTTP_303_SEE_OTHER)
    return await _finish_sso(request, "oauth", slug, params)


@router.post("/sso/saml/{slug}", include_in_schema=False)
async def sso_saml_callback(slug: str, request: Request) -> Response:
    """The SAML IdP's POST to ``/source/saml/<slug>/acs/`` (Caddy)."""
    body = await request.body()
    params = None
    if len(body) <= MAX_SAML_BODY:
        try:
            pairs = parse_qsl(body.decode("ascii"), keep_blank_values=True, strict_parsing=False)
        except UnicodeDecodeError:
            pairs = []
        params = _bounded(pairs, MAX_SAML_BODY)
    if not params:
        return RedirectResponse(SSO_FAILED_REDIRECT, status_code=status.HTTP_303_SEE_OTHER)
    return await _finish_sso(request, "saml", slug, params)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> Response:
    """Clear the session cookie and revoke the session server-side (P1a-02): the token
    is listed in ``revoked_sessions``, so a copy of the old cookie is refused."""
    state = request.app.state
    token = presented_token(request.scope)
    if state.settings.models.auth.mode == "oidc" and token is not None:
        await revoke(
            state.db_factory,
            state.token_validator,
            getattr(state, "sign_in_provider", None),
            token,
        )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return response
