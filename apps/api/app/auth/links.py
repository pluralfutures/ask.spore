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
- **Second factor for tenant admins (P1b-08).** Authentik asks members of its admin
  group for a TOTP code in the link flow; the API relays the challenge to the browser
  holding the link's binding (``complete_mfa``, at most 5 codes in 5 minutes) and
  refuses a tenant admin whose tenant requires it if the flow did not include it.
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
from app.auth.models import MAX_MFA_ATTEMPTS, MfaChallenge, SignInLink
from app.auth.provider import (
    IssuedTokens,
    LinkRefused,
    MfaRequired,
    ProviderError,
    SignInLinkProvider,
)
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
MAX_RESUME_LENGTH: Final = 4096
MFA_TTL: Final = timedelta(minutes=5)


class SignInRefused(Exception):
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


@dataclass(frozen=True)
class SignedIn:
    context: RequestContext
    access_token: str
    expires_at: datetime
    refresh_token: str | None = None  # P1b-08


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


@dataclass(frozen=True)
class MfaPending:
    """The flow waits for the user's second factor (P1b-08). ``binding`` is the secret
    for the browser's MFA cookie; ``challenge`` what Authentik asks for."""

    binding: str
    challenge: MfaRequired


async def complete_link(
    *,
    factory: async_sessionmaker[AsyncSession],
    provider: SignInLinkProvider,
    validator: TokenValidator,
    token: str,
    binding: str | None,
) -> SignedIn | MfaPending:
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
        redeemed = await provider.redeem_sign_in_link(token)
    except (LinkRefused, ProviderError) as exc:
        await refuse_sign_in(factory, pending.tenant_id, pending.user_id, exc.error_code)
    if isinstance(redeemed, MfaRequired):
        return await _hold_for_mfa(factory, pending, redeemed)
    return await _finish(factory, provider, validator, pending, redeemed)


# --- the second factor for tenant admins (P1b-08) -----------------------------------------


async def _hold_for_mfa(
    factory: async_sessionmaker[AsyncSession], pending: _Pending, challenge: MfaRequired
) -> MfaPending:
    binding = new_binding()
    async with role_session(factory, AUTH_ROLE) as session:
        session.add(
            MfaChallenge(
                tenant_id=pending.tenant_id,
                user_id=pending.user_id,
                binding_hash=digest(binding),
                expires_at=func.now() + MFA_TTL,
            )
        )
    log("auth.mfa_required", tenant_id=str(pending.tenant_id), user_id=str(pending.user_id))
    return MfaPending(binding=binding, challenge=challenge)


async def _claim_mfa(
    factory: async_sessionmaker[AsyncSession], binding_hash: str
) -> tuple[_Pending | None, int, str | None, UUID | None]:
    """Count one code against the browser's challenge: (pending, attempts, refusal, tenant)."""
    async with role_session(factory, AUTH_ROLE) as session:
        row = (
            await session.execute(
                select(
                    MfaChallenge.id,
                    MfaChallenge.tenant_id,
                    MfaChallenge.user_id,
                    MfaChallenge.completed_at,
                    (MfaChallenge.expires_at <= func.now()).label("expired"),
                ).where(MfaChallenge.binding_hash == binding_hash)
            )
        ).one_or_none()
        if row is None:
            return None, 0, "unknown_binding", None
        if row.completed_at is not None:
            return None, 0, "used", row.tenant_id
        if row.expired:
            return None, 0, "expired", row.tenant_id
        attempts = await session.scalar(
            update(MfaChallenge)
            .where(MfaChallenge.id == row.id, MfaChallenge.attempts < MAX_MFA_ATTEMPTS)
            .values(attempts=MfaChallenge.attempts + 1)
            .returning(MfaChallenge.attempts)
        )
        if attempts is None:
            return None, 0, "too_many_attempts", row.tenant_id
        email = await session.scalar(
            select(User.email).where(User.tenant_id == row.tenant_id, User.id == row.user_id)
        )
        if email is None:
            return None, 0, "user_inactive", row.tenant_id
        return _Pending(row.tenant_id, row.user_id, email), attempts, None, row.tenant_id


async def complete_mfa(
    *,
    factory: async_sessionmaker[AsyncSession],
    provider: SignInLinkProvider,
    validator: TokenValidator,
    binding: str | None,
    resume: str | None,
    code: str,
) -> SignedIn | MfaPending:
    """Relay the user's code to the pending challenge, from the browser holding it."""
    if not binding or not resume or len(resume) > MAX_RESUME_LENGTH:
        await refuse_sign_in(factory, None, None, "no_binding")
    pending, attempts, refusal, tenant_id = await _claim_mfa(factory, digest(binding))
    if pending is None:
        await refuse_sign_in(factory, tenant_id, None, refusal or "unknown_binding")
    try:
        answered = await provider.answer_mfa(resume, code)
    except (LinkRefused, ProviderError) as exc:
        await refuse_sign_in(factory, pending.tenant_id, pending.user_id, exc.error_code)
    if isinstance(answered, MfaRequired):
        await audit_sign_in(
            factory, pending.tenant_id, pending.user_id, "auth.mfa_failed", "mfa_code_refused"
        )
        if attempts >= MAX_MFA_ATTEMPTS:
            await refuse_sign_in(factory, pending.tenant_id, pending.user_id, "too_many_attempts")
        return MfaPending(binding=binding, challenge=answered)
    async with role_session(factory, AUTH_ROLE) as session:
        await session.execute(
            update(MfaChallenge)
            .where(MfaChallenge.binding_hash == digest(binding))
            .values(completed_at=func.now())
        )
    return await _finish(factory, provider, validator, pending, answered)


async def _finish(
    factory: async_sessionmaker[AsyncSession],
    provider: SignInLinkProvider,
    validator: TokenValidator,
    pending: _Pending,
    issued: IssuedTokens,
) -> SignedIn:
    """Check the provider's token against the link's user and record the sign-in."""
    try:
        identity = await validator.validate(issued.access_token)
    except InvalidToken as exc:
        await refuse_sign_in(factory, pending.tenant_id, pending.user_id, exc.error_code)
    if identity.tenant_id != pending.tenant_id or identity.email != pending.email:
        await refuse_sign_in(factory, pending.tenant_id, pending.user_id, "identity_mismatch")

    context = await resolve_user(factory, pending.tenant_id, pending.email, allow_invited=True)
    if context is None or context.user_id != pending.user_id:
        await refuse_sign_in(factory, pending.tenant_id, pending.user_id, "user_inactive")
    async with tenant_session(factory, pending.tenant_id) as session:
        policy = (
            await session.execute(
                select(
                    TenantLoginPolicy.sign_in_links_enabled,
                    TenantLoginPolicy.admin_mfa_required,
                ).where(TenantLoginPolicy.tenant_id == pending.tenant_id)
            )
        ).one_or_none()
        enabled = policy is not None and policy.sign_in_links_enabled
        mfa_missing = (
            context.is_tenant_admin and (policy is None or policy.admin_mfa_required)
        ) and not issued.mfa
        if enabled and not mfa_missing:
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
                metadata={"method": METHOD, "status": "ok", "mfa": issued.mfa},
            )
    if not enabled:
        await refuse_sign_in(factory, pending.tenant_id, pending.user_id, "links_disabled")
    if mfa_missing:
        # Fail closed (P1b-08): a tenant admin got through without the second factor,
        # which means Authentik does not have them in the group the stage is bound to
        # (before their first sign-in since the requirement, or out of step). The tokens
        # are revoked and they are put in the group, so their next link asks for it.
        await _revoke_issued(provider, issued)
        try:
            await provider.set_admin_mfa(pending.email, True)
        except ProviderError as exc:
            log("auth.mfa_group_not_updated", level="error", error_code=exc.error_code)
        await refuse_sign_in(factory, pending.tenant_id, pending.user_id, "mfa_not_enforced")
    log("auth.login", tenant_id=str(pending.tenant_id), user_id=str(pending.user_id), status="ok")
    return SignedIn(
        context=RequestContext(
            tenant_id=context.tenant_id, user_id=context.user_id, role=context.role
        ),
        access_token=issued.access_token,
        expires_at=identity.expires_at,
        refresh_token=issued.refresh_token,
    )


async def _revoke_issued(provider: SignInLinkProvider, issued: IssuedTokens) -> None:
    try:
        await provider.revoke_token(issued.access_token, "access_token")
        if issued.refresh_token:
            await provider.revoke_token(issued.refresh_token, "refresh_token")
    except ProviderError as exc:
        log("auth.provider_revoke_failed", level="warning", error_code=exc.error_code)


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
