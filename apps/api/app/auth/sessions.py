"""Sign-out revokes the session (P1a-02, owner decision on Group A's open question).

The session is the Authentik access token in the ``askspore_session`` cookie, which
the API validates locally against Authentik's JWKS. Clearing the cookie alone would
leave a copied token usable until it expires, so ``revoke`` also records the token's
SHA-256 in ``revoked_sessions`` (tenant-scoped, RLS), which authentication checks on
every request (``app.tenancy.context.resolve_user``), and asks Authentik to revoke
the token too (RFC 7009, best effort: our own list is the control the API relies on).

No token, hash or email is logged; the audit row names the user only.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.auth.middleware import token_digest
from app.auth.models import RevokedSession
from app.auth.provider import ProviderError, SignInLinkProvider
from app.auth.tokens import InvalidToken, TokenValidator
from app.core.db import tenant_session
from app.core.logging import log
from app.tenancy.context import resolve_user


async def revoke(
    factory: async_sessionmaker[AsyncSession],
    validator: TokenValidator,
    provider: SignInLinkProvider | None,
    token: str,
) -> bool:
    """Revoke ``token`` if it is a valid, unrevoked session of an active user.

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
    async with tenant_session(factory, context.tenant_id) as session:
        await session.execute(
            insert(RevokedSession)
            .values(
                tenant_id=context.tenant_id,
                token_sha256=digest,
                user_id=context.user_id,
                expires_at=identity.expires_at,
            )
            .on_conflict_do_nothing()
        )
        await record(
            session,
            tenant_id=context.tenant_id,
            actor_user_id=context.user_id,
            event="auth.signed_out",
            metadata={"status": "revoked"},
        )
    log("auth.signed_out", tenant_id=str(context.tenant_id), user_id=str(context.user_id))
    if provider is not None:
        try:
            await provider.revoke_token(token)
        except ProviderError as exc:
            log("auth.provider_revoke_failed", level="warning", error_code=exc.error_code)
    return True
