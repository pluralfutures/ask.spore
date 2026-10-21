"""Sign-in links: request, and the post-click completion (P1a-02).

Controls (compliance guide, addendum of Oct 17, 2026; architecture §4.3 and §8),
enforced here whatever the provider does:

- **No enumeration.** ``POST /auth/link`` answers the same way, with the same
  binding cookie, for every address; the lookup and the send run after the response.
  A link is sent only when the address names exactly one invited or active user of an
  active tenant whose login policy has sign-in links on (P1b-06).
- **Browser binding.** The request sets a random binding secret in an HttpOnly,
  SameSite=Strict cookie on the requesting browser; only its SHA-256 is stored, on
  the ``sign_in_links`` row. Completion needs that cookie: a link opened in another
  browser (or by a mail scanner) is refused *before* the token reaches the provider,
  so it is not spent.
- **Nothing is consumed by a GET.** The emailed link opens our landing page with the
  token in the URL fragment; only the page's button POSTs it (``app.api.auth``).
- **One POST per link, 15 minutes at most.** The first POST for a binding consumes
  it and records the token's SHA-256; any later POST with that binding or that token
  is refused without calling the provider. Expired rows are refused.
- **Identity check.** The provider's token must name the same tenant and email as the
  row the binding points to.
- **Audit.** Success and failure write ``audit_events`` with the method; failures
  that cannot be attributed to a tenant are recorded under the internal (platform)
  tenant. Logs carry error codes only, never an email or a token.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, NoReturn
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import AuditValue, record
from app.auth.models import SignInLink
from app.auth.provider import LinkRefused, ProviderError, SignInLinkProvider
from app.auth.tokens import InvalidToken, TokenValidator
from app.core.config import AuthConfig
from app.core.db import AUTH_ROLE, role_session, tenant_session
from app.core.logging import log
from app.tenancy.context import RequestContext, resolve_user
from app.tenancy.login_policy import TenantLoginPolicy
from app.tenancy.models import INTERNAL_TENANT_ID, Tenant, User

METHOD: Final = "sign_in_link"
MAX_EMAIL_LENGTH: Final = 320
MAX_TOKEN_LENGTH: Final = 512


class SignInRefused(Exception):
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


@dataclass(frozen=True)
class SignedIn:
    context: RequestContext
    access_token: str
    expires_at: datetime


def new_binding() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalise_email(raw: str) -> str | None:
    email = raw.strip().lower()
    local, at, domain = email.partition("@")
    if not at or not local or "." not in domain or len(email) > MAX_EMAIL_LENGTH:
        return None
    if any(c.isspace() for c in email) or "@" in domain:
        return None
    return email


# --- request ---------------------------------------------------------------------------


async def request_link(
    *,
    factory: async_sessionmaker[AsyncSession],
    provider: SignInLinkProvider,
    config: AuthConfig,
    email: str,
    binding: str,
) -> None:
    """Send a link if ``email`` may sign in with one. Runs after the response; never raises."""
    try:
        await _request_link(factory, provider, config, email, binding)
    except ProviderError as exc:
        log("auth.link_not_sent", level="error", error_code=exc.error_code)
    except Exception:  # background task: nothing may surface to the requester
        log("auth.link_not_sent", level="error", error_code="internal_error")


async def _request_link(
    factory: async_sessionmaker[AsyncSession],
    provider: SignInLinkProvider,
    config: AuthConfig,
    raw_email: str,
    binding: str,
) -> None:
    email = normalise_email(raw_email)
    if email is None:
        log("auth.link_not_sent", error_code="malformed_email")
        return
    async with role_session(factory, AUTH_ROLE) as session:
        candidates = (
            await session.execute(
                select(User.id, User.tenant_id)
                .join(Tenant, Tenant.id == User.tenant_id)
                .join(TenantLoginPolicy, TenantLoginPolicy.tenant_id == User.tenant_id)
                .where(
                    User.email == email,
                    User.status.in_(("invited", "active")),
                    Tenant.status == "active",
                    TenantLoginPolicy.sign_in_links_enabled.is_(True),
                )
            )
        ).all()
        if len(candidates) != 1:
            # Unknown, not allowed, or (never by construction) in two tenants.
            log("auth.link_not_sent", error_code="no_eligible_user")
            return
        user_id, tenant_id = candidates[0]
        window = timedelta(seconds=config.link_ttl_seconds)
        recent = await session.scalar(
            select(func.count())
            .select_from(SignInLink)
            .where(
                SignInLink.tenant_id == tenant_id,
                SignInLink.user_id == user_id,
                SignInLink.created_at > func.now() - window,
            )
        )
        if (recent or 0) >= config.links_per_window:
            limited = True
        else:
            limited = False
            session.add(
                SignInLink(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    binding_hash=digest(binding),
                    expires_at=func.now() + window,  # the database's clock
                )
            )
    if limited:
        await audit_sign_in(factory, tenant_id, user_id, "auth.link_refused", "rate_limited")
        log("auth.link_not_sent", tenant_id=str(tenant_id), error_code="rate_limited")
        return
    await provider.send_sign_in_link(email)
    await audit_sign_in(factory, tenant_id, user_id, "auth.link_requested", None)
    log("auth.link_sent", tenant_id=str(tenant_id), user_id=str(user_id))


# --- completion --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Pending:
    tenant_id: UUID
    user_id: UUID
    email: str


async def _consume(
    factory: async_sessionmaker[AsyncSession], token_hash: str, binding_hash: str
) -> tuple[_Pending | None, str | None, UUID | None]:
    """Consume the binding's row for this token: (pending, refusal code, tenant to audit)."""
    try:
        async with role_session(factory, AUTH_ROLE) as session:
            row = (
                await session.execute(
                    select(
                        SignInLink.id,
                        SignInLink.tenant_id,
                        SignInLink.user_id,
                        SignInLink.consumed_at,
                        (SignInLink.expires_at <= func.now()).label("expired"),
                    ).where(SignInLink.binding_hash == binding_hash)
                )
            ).one_or_none()
            reused = await session.scalar(
                select(SignInLink.tenant_id).where(SignInLink.token_hash == token_hash)
            )
            if reused is not None:
                return None, "used", reused
            if row is None:
                return None, "unknown_binding", None
            if row.consumed_at is not None:
                return None, "used", row.tenant_id
            if row.expired:
                return None, "expired", row.tenant_id
            consumed = await session.scalar(
                update(SignInLink)
                .where(SignInLink.id == row.id, SignInLink.consumed_at.is_(None))
                .values(consumed_at=func.now(), token_hash=token_hash)
                .returning(SignInLink.id)
            )
            if consumed is None:
                return None, "used", row.tenant_id
            email = await session.scalar(
                select(User.email).where(User.tenant_id == row.tenant_id, User.id == row.user_id)
            )
            if email is None:
                return None, "user_inactive", row.tenant_id
            return _Pending(row.tenant_id, row.user_id, email), None, row.tenant_id
    except IntegrityError:
        # The same token consumed concurrently under another binding.
        return None, "used", None


async def complete_link(
    *,
    factory: async_sessionmaker[AsyncSession],
    provider: SignInLinkProvider,
    validator: TokenValidator,
    token: str,
    binding: str | None,
) -> SignedIn:
    """Redeem a link token POSTed from the landing page by the browser holding ``binding``."""
    if not binding:
        # Another browser or a scanner: refused before anything is consumed.
        await refuse_sign_in(factory, None, None, "no_binding")
    if not token or len(token) > MAX_TOKEN_LENGTH:
        await refuse_sign_in(factory, None, None, "malformed_token")
    pending, refusal, tenant_id = await _consume(factory, digest(token), digest(binding))
    if pending is None:
        await refuse_sign_in(factory, tenant_id, None, refusal or "unknown_binding")

    try:
        issued = await provider.redeem_sign_in_link(token)
        identity = await validator.validate(issued.access_token)
    except (LinkRefused, ProviderError, InvalidToken) as exc:
        await refuse_sign_in(factory, pending.tenant_id, pending.user_id, exc.error_code)
    if identity.tenant_id != pending.tenant_id or identity.email != pending.email:
        await refuse_sign_in(factory, pending.tenant_id, pending.user_id, "identity_mismatch")

    context = await resolve_user(factory, pending.tenant_id, pending.email, allow_invited=True)
    if context is None or context.user_id != pending.user_id:
        await refuse_sign_in(factory, pending.tenant_id, pending.user_id, "user_inactive")
    async with tenant_session(factory, pending.tenant_id) as session:
        enabled = await session.scalar(
            select(TenantLoginPolicy.sign_in_links_enabled).where(
                TenantLoginPolicy.tenant_id == pending.tenant_id
            )
        )
        if enabled:
            await session.execute(
                update(User)
                .where(User.tenant_id == pending.tenant_id, User.id == pending.user_id)
                .values(status="active", last_login_at=func.now(), last_login_method=METHOD)
            )
            await record(
                session,
                tenant_id=pending.tenant_id,
                actor_user_id=pending.user_id,
                event="auth.login",
                metadata={"method": METHOD, "status": "ok"},
            )
    if not enabled:
        await refuse_sign_in(factory, pending.tenant_id, pending.user_id, "links_disabled")
    log("auth.login", tenant_id=str(pending.tenant_id), user_id=str(pending.user_id), status="ok")
    return SignedIn(
        context=RequestContext(
            tenant_id=context.tenant_id, user_id=context.user_id, role=context.role
        ),
        access_token=issued.access_token,
        expires_at=identity.expires_at,
    )


async def refuse_sign_in(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID | None,
    user_id: UUID | None,
    error_code: str,
    *,
    method: str = METHOD,
) -> NoReturn:
    """Audit and log a failed completion, then raise SignInRefused."""
    await audit_sign_in(
        factory,
        tenant_id or INTERNAL_TENANT_ID,
        user_id,
        "auth.login_failed",
        error_code,
        method=method,
    )
    log(
        "auth.login_failed",
        tenant_id=str(tenant_id) if tenant_id else None,
        error_code=error_code,
    )
    raise SignInRefused(error_code)


async def audit_sign_in(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    user_id: UUID | None,
    event: str,
    error_code: str | None,
    *,
    method: str = METHOD,
) -> None:
    metadata: dict[str, AuditValue] = {"method": method}
    if error_code is not None:
        metadata["error_code"] = error_code
    async with tenant_session(factory, tenant_id) as session:
        await record(
            session,
            tenant_id=tenant_id,
            actor_user_id=user_id,
            event=event,
            metadata=metadata,
        )
