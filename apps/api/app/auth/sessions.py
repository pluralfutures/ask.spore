"""Sign-out revokes the session (P1a-02); the session is renewed before it expires
(P1b-08).

The session is the Authentik access token in the ``askspore_session`` cookie, which
the API validates locally against Authentik's JWKS, and, from P1b-08, a refresh token
in the ``askspore_refresh`` cookie (HttpOnly, sent to the auth routes only).

- **Sign-out** (``revoke``): clearing the cookies alone would leave a copied token
  usable, so the SHA-256 of the access token, and of the refresh token, is recorded in
  ``revoked_sessions`` (tenant-scoped, RLS), and Authentik is asked to revoke both
  (RFC 7009, best effort). Authentication refuses a listed access token on every
  request (``app.tenancy.context.resolve_user``); the refresh route refuses a listed
  refresh token even if Authentik would still honour it.
- **Refresh** (``refresh``): the web app calls it before the access token expires.
  Authentik rotates the refresh token; the API also lists the old refresh token and the
  previous access token as revoked, so neither can be used again, and requires the new
  token to name the same user, still active in an active tenant.

No token, hash or email is logged; audit rows name the user only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.auth.links import SignedIn, SignInRefused
from app.auth.middleware import token_digest
from app.auth.models import RevokedSession
from app.auth.provider import LinkRefused, ProviderError, SignInLinkProvider, TokenKind
from app.auth.tokens import Identity, InvalidToken, TokenValidator
from app.core.db import tenant_session
from app.core.logging import log
from app.tenancy.context import RequestContext, resolve_user

MAX_REFRESH_TOKEN_LENGTH: Final = 4096


async def _list_revoked(
    session: AsyncSession,
    context: RequestContext,
    tokens: list[tuple[str, datetime]],
) -> None:
    for token, expires_at in tokens:
        await session.execute(
            insert(RevokedSession)
            .values(
                tenant_id=context.tenant_id,
                token_sha256=token_digest(token),
                user_id=context.user_id,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing()
        )


async def _revoke_at_provider(
    provider: SignInLinkProvider | None, token: str, kind: TokenKind
) -> None:
    if provider is None:
        return
    try:
        await provider.revoke_token(token, kind)
    except ProviderError as exc:
        log("auth.provider_revoke_failed", level="warning", error_code=exc.error_code)


async def revoke(
    factory: async_sessionmaker[AsyncSession],
    validator: TokenValidator,
    provider: SignInLinkProvider | None,
    token: str,
    *,
    refresh_token: str | None = None,
    refresh_ttl_seconds: int = 86_400,
) -> bool:
    """Revoke ``token`` (and ``refresh_token``) if it is a valid, unrevoked session of an
    active user.

    Returns whether anything was revoked. An invalid, expired or already revoked token
    revokes nothing: it is refused by authentication anyway.
    """
    try:
        identity = await validator.validate(token)
    except InvalidToken:
        return False
    digest = token_digest(token)
    context = await resolve_user(factory, identity.tenant_id, identity.email, token_sha256=digest)
    if context is None:
        return False
    revoked = [(token, identity.expires_at)]
    if refresh_token and len(refresh_token) <= MAX_REFRESH_TOKEN_LENGTH:
        revoked.append((refresh_token, datetime.now(UTC) + timedelta(seconds=refresh_ttl_seconds)))
    async with tenant_session(factory, context.tenant_id) as session:
        await _list_revoked(session, context, revoked)
        await record(
            session,
            tenant_id=context.tenant_id,
            actor_user_id=context.user_id,
            event="auth.signed_out",
            metadata={"status": "revoked"},
        )
    log("auth.signed_out", tenant_id=str(context.tenant_id), user_id=str(context.user_id))
    await _revoke_at_provider(provider, token, "access_token")
    if refresh_token:
        await _revoke_at_provider(provider, refresh_token, "refresh_token")
    return True


async def _listed(factory: async_sessionmaker[AsyncSession], tenant_id: UUID, token: str) -> bool:
    async with tenant_session(factory, tenant_id) as session:
        listed = await session.scalar(
            select(
                exists().where(
                    RevokedSession.tenant_id == tenant_id,
                    RevokedSession.token_sha256 == token_digest(token),
                )
            )
        )
    return bool(listed)


async def refresh(
    *,
    factory: async_sessionmaker[AsyncSession],
    validator: TokenValidator,
    provider: SignInLinkProvider,
    refresh_token: str | None,
    current_token: str | None,
    refresh_ttl_seconds: int,
) -> SignedIn:
    """Renew the session from the refresh cookie; raise SignInRefused (error code only)."""
    if not refresh_token or len(refresh_token) > MAX_REFRESH_TOKEN_LENGTH:
        raise SignInRefused("no_refresh_token")
    current: Identity | None = None
    if current_token:
        try:
            current = await validator.validate(current_token)
        except InvalidToken:
            current = None  # expired: the refresh token alone may renew the session
    try:
        issued = await provider.refresh_session(refresh_token)
        identity = await validator.validate(issued.access_token)
    except (LinkRefused, ProviderError, InvalidToken) as exc:
        log("auth.refresh_refused", error_code=exc.error_code)
        raise SignInRefused("refresh_refused") from None

    async def refuse(code: str) -> SignInRefused:
        # Whatever Authentik just issued is revoked again: nobody gets to use it.
        await _revoke_at_provider(provider, issued.access_token, "access_token")
        if issued.refresh_token:
            await _revoke_at_provider(provider, issued.refresh_token, "refresh_token")
        log("auth.refresh_refused", tenant_id=str(identity.tenant_id), error_code=code)
        return SignInRefused(code)

    if await _listed(factory, identity.tenant_id, refresh_token):
        # Signed out with this refresh token: our own list decides, whatever Authentik did.
        raise await refuse("revoked")
    if current is not None and (current.tenant_id, current.email) != (
        identity.tenant_id,
        identity.email,
    ):
        raise await refuse("identity_mismatch")
    context = await resolve_user(factory, identity.tenant_id, identity.email)
    if context is None:
        raise await refuse("user_inactive")
    spent = [(refresh_token, datetime.now(UTC) + timedelta(seconds=refresh_ttl_seconds))]
    if current is not None and current_token is not None:
        spent.append((current_token, current.expires_at))
    async with tenant_session(factory, context.tenant_id) as session:
        await _list_revoked(session, context, spent)
        await record(
            session,
            tenant_id=context.tenant_id,
            actor_user_id=context.user_id,
            event="auth.session_refreshed",
            metadata={"status": "ok"},
        )
    log("auth.session_refreshed", tenant_id=str(context.tenant_id), user_id=str(context.user_id))
    return SignedIn(
        context=context,
        access_token=issued.access_token,
        expires_at=identity.expires_at,
        refresh_token=issued.refresh_token,
    )
