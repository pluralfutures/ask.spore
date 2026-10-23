"""Sign-in through a tenant's SSO source in Authentik (P1b-07; architecture §4.3).

Flow: the login page sends the address (``POST /auth/sso/start``); its domain resolves
to one tenant (``app.tenancy.login_policy.discover``) and that tenant's source. The API
starts the source's login at Authentik on the Compose network, records an
``sso_attempts`` row bound to this browser (only the SHA-256 of a random binding
secret is stored; the secret and Authentik's pending state stay in the browser's
cookies) and sends the browser to the IdP. The IdP sends the browser back to our
public host under Authentik's callback path, which Caddy hands to the API
(``app.api.auth``); the API passes the answer on to Authentik, which signs the user
in through the source, and the API then runs the OIDC code flow as for sign-in links.

Controls, enforced here whatever the IdP and Authentik say:

- **The tenant comes from the attempt, never from the IdP.** The attempt's tenant is
  the one the address's domain resolved to when the sign-in started. The token must
  name that tenant (the source's property mapping stamps it at provisioning from the
  source's own tenant, never from a claim) and that source (``ask_spore_sso.source``),
  and the source must still be the tenant's. A token from a source bound to tenant A
  therefore never signs anyone into tenant B.
- **Verified domains only.** The address must be at one of the tenant's verified
  domains; for Google Workspace the ``hd`` claim must be one too; the IdP must have
  verified the address.
- **Just-in-time provisioning** creates the ``users`` row only when the tenant's policy
  has JIT on, the domain is verified, and the address is not a user of any other
  tenant; otherwise the sign-in is refused unless the user was invited.
- **Entra group mapping** (optional): when the source names admin groups, the user's
  role follows membership at every sign-in (audited when it changes).
- **Browser binding, single use, 10 minutes**, as for links: the callback needs the
  starting browser's cookie, and the attempt is consumed before Authentik is called.
- **Audit**: login (``auth.login``), failed login (``auth.login_failed`` with an error
  code), and provisioning (``auth.user_provisioned``), with ``method`` ``sso:<kind>``
  (P1c-02) once the attempt's source is known, ``sso`` before (another browser, an
  unknown, used or expired attempt). Logs carry codes and IDs only, never an address, a
  token or the IdP's answer.
- **Refusals by the source** (P1c-02): the source's mapping refuses an address outside
  the verified domains, a Google ``hd`` outside them and an unverified address as a
  return value; Authentik denies the flow with the code (no user written there, no
  exception) and the API audits that code. The browser lands on the sign-in page with a
  coarse reason (``refusal_reason``), never the code itself.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Literal, NoReturn
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.auth.links import (
    SignedIn,
    digest,
    new_binding,
    normalise_email,
    refuse_sign_in,
)
from app.auth.models import SsoAttempt
from app.auth.provider import LinkRefused, ProviderError, SsoProvider
from app.auth.tokens import InvalidToken, TokenValidator
from app.core.db import AUTH_ROLE, role_session, tenant_session
from app.core.logging import log
from app.tenancy.context import RequestContext, resolve_user
from app.tenancy.login_policy import SSO_KINDS, SsoKind, TenantLoginPolicy, discover
from app.tenancy.models import Tenant, User

METHOD: Final = "sso"  # users.last_login_method, and audits before the kind is known
ATTEMPT_TTL: Final = timedelta(minutes=10)
MAX_RESUME_LENGTH: Final = 4096
CallbackKind = Literal["oauth", "saml"]


@dataclass(frozen=True)
class SsoStarted:
    redirect_url: str
    binding: str
    resume: str
    callback: CallbackKind


def callback_kind(kind: SsoKind) -> CallbackKind:
    return "saml" if kind == "saml" else "oauth"


def audit_method(kind: SsoKind) -> str:
    """The audit events' ``method`` for a sign-in through a source of ``kind`` (P1c-02)."""
    return f"{METHOD}:{kind}"


# P1c-02: what the sign-in page may say about a refusal. Codes that would tell an
# outsider something about another tenant's users (``email_in_other_tenant``) share the
# answer of an uninvited address; anything unlisted is the generic failure.
REFUSAL_REASONS: Final[Mapping[str, str]] = {
    "domain_not_verified": "domain",
    "hd_mismatch": "domain",
    "email_unverified": "unverified",
    "not_invited": "no_access",
    "email_in_other_tenant": "no_access",
    "user_inactive": "no_access",
    "no_binding": "start_again",
    "unknown_binding": "start_again",
    "used": "start_again",
    "expired": "start_again",
}


def refusal_reason(error_code: str) -> str:
    return REFUSAL_REASONS.get(error_code, "failed")


async def start(
    *, factory: async_sessionmaker[AsyncSession], provider: SsoProvider, email: str
) -> SsoStarted | None:
    """Start a sign-in through the source of the address's tenant, if it has one.

    ``None`` for an unknown domain and for a domain without SSO alike: the route
    answers both the same way.
    """
    found = await discover(factory, email)
    if found.sso_kind is None or found.tenant_id is None or found.sso_source_slug is None:
        log("auth.sso_not_started", error_code="no_source")
        return None
    redirect = await provider.start_sso(found.sso_kind, found.sso_source_slug)
    binding = new_binding()
    async with role_session(factory, AUTH_ROLE) as session:
        session.add(
            SsoAttempt(
                tenant_id=found.tenant_id,
                binding_hash=digest(binding),
                source_slug=found.sso_source_slug,
                expires_at=func.now() + ATTEMPT_TTL,  # the database's clock
            )
        )
    log("auth.sso_started", tenant_id=str(found.tenant_id))
    return SsoStarted(
        redirect_url=redirect.url,
        binding=binding,
        resume=redirect.resume,
        callback=callback_kind(found.sso_kind),
    )


@dataclass(frozen=True)
class _Attempt:
    tenant_id: UUID
    source_slug: str


async def _consume(
    factory: async_sessionmaker[AsyncSession], binding_hash: str, path_slug: str
) -> tuple[_Attempt | None, str | None, UUID | None]:
    """Consume the browser's attempt: (attempt, refusal code, tenant to audit)."""
    async with role_session(factory, AUTH_ROLE) as session:
        row = (
            await session.execute(
                select(
                    SsoAttempt.id,
                    SsoAttempt.tenant_id,
                    SsoAttempt.source_slug,
                    SsoAttempt.consumed_at,
                    (SsoAttempt.expires_at <= func.now()).label("expired"),
                ).where(SsoAttempt.binding_hash == binding_hash)
            )
        ).one_or_none()
        if row is None:
            return None, "unknown_binding", None
        if row.consumed_at is not None:
            return None, "used", row.tenant_id
        if row.expired:
            return None, "expired", row.tenant_id
        consumed = await session.scalar(
            update(SsoAttempt)
            .where(SsoAttempt.id == row.id, SsoAttempt.consumed_at.is_(None))
            .values(consumed_at=func.now())
            .returning(SsoAttempt.id)
        )
        if consumed is None:
            return None, "used", row.tenant_id
        if row.source_slug != path_slug:
            # The IdP's answer arrived at another source's callback.
            return None, "source_mismatch", row.tenant_id
        return _Attempt(row.tenant_id, row.source_slug), None, row.tenant_id


@dataclass(frozen=True)
class _Tenant:
    kind: SsoKind
    verified_domains: tuple[str, ...]
    jit: bool
    admin_groups: tuple[str, ...]


async def _tenant(factory: async_sessionmaker[AsyncSession], attempt: _Attempt) -> _Tenant | None:
    """The attempt's tenant, if it is active and its source is still the attempt's."""
    async with role_session(factory, AUTH_ROLE) as session:
        row = (
            await session.execute(
                select(
                    Tenant.verified_domains,
                    TenantLoginPolicy.sso_source_kind,
                    TenantLoginPolicy.jit_provisioning_enabled,
                )
                .join(TenantLoginPolicy, TenantLoginPolicy.tenant_id == Tenant.id)
                .where(
                    Tenant.id == attempt.tenant_id,
                    Tenant.status == "active",
                    TenantLoginPolicy.sso_source_slug == attempt.source_slug,
                )
            )
        ).one_or_none()
    if row is None or row.sso_source_kind not in SSO_KINDS:
        return None
    # The admin-group mapping is configuration the pre-authentication role cannot read
    # (sso_source_config); read it in the tenant's own scope.
    async with tenant_session(factory, attempt.tenant_id) as session:
        config = await session.scalar(
            select(TenantLoginPolicy.sso_source_config).where(
                TenantLoginPolicy.tenant_id == attempt.tenant_id
            )
        )
    groups = (config or {}).get("admin_group_ids") or []
    kind: SsoKind = row.sso_source_kind
    return _Tenant(
        kind=kind,
        verified_domains=tuple(row.verified_domains),
        jit=row.jit_provisioning_enabled,
        admin_groups=tuple(str(g) for g in groups) if kind == "entra" else (),
    )


async def complete(
    *,
    factory: async_sessionmaker[AsyncSession],
    provider: SsoProvider,
    validator: TokenValidator,
    callback: CallbackKind,
    slug: str,
    params: Mapping[str, str],
    binding: str | None,
    resume: str | None,
) -> SignedIn:
    """Finish a sign-in from the IdP's answer, arriving in the browser that started it."""

    method = METHOD

    async def refuse(tenant_id: UUID | None, user_id: UUID | None, code: str) -> NoReturn:
        await refuse_sign_in(factory, tenant_id, user_id, code, method=method)

    if not binding or not resume or len(resume) > MAX_RESUME_LENGTH:
        # Another browser, or cookies lost: refused before anything is consumed.
        await refuse(None, None, "no_binding")
    attempt, refusal, tenant_id = await _consume(factory, digest(binding), slug)
    if attempt is None:
        await refuse(tenant_id, None, refusal or "unknown_binding")
    tenant = await _tenant(factory, attempt)
    if tenant is None or callback_kind(tenant.kind) != callback:
        await refuse(attempt.tenant_id, None, "source_changed")
    method = audit_method(tenant.kind)

    try:
        issued = await provider.finish_sso(tenant.kind, attempt.source_slug, params, resume)
        identity = await validator.validate(issued.access_token)
    except (LinkRefused, ProviderError, InvalidToken) as exc:
        await refuse(attempt.tenant_id, None, exc.error_code)

    # The tenant is the attempt's; the token must agree, and must come from its source.
    if identity.tenant_id != attempt.tenant_id:
        await refuse(attempt.tenant_id, None, "tenant_mismatch")
    if identity.sso is None or identity.sso.source != attempt.source_slug:
        await refuse(attempt.tenant_id, None, "source_mismatch")
    email = normalise_email(identity.email)
    domain = email.partition("@")[2] if email else ""
    if email is None or domain not in tenant.verified_domains:
        await refuse(attempt.tenant_id, None, "domain_not_verified")
    if tenant.kind == "google" and identity.sso.hd not in tenant.verified_domains:
        await refuse(attempt.tenant_id, None, "hd_mismatch")
    if not identity.sso.email_verified:
        await refuse(attempt.tenant_id, None, "email_unverified")

    role = None
    if tenant.admin_groups:
        role = "tenant_admin" if identity.sso.admin else "user"
    user_id, refusal = await _sign_in_user(
        factory, attempt.tenant_id, email, tenant.jit, role, method
    )
    if user_id is None:
        await refuse(attempt.tenant_id, None, refusal or "not_invited")
    context = await resolve_user(factory, attempt.tenant_id, email)
    if context is None or context.user_id != user_id:
        await refuse(attempt.tenant_id, user_id, "user_inactive")
    log("auth.login", tenant_id=str(context.tenant_id), user_id=str(context.user_id), status="ok")
    return SignedIn(
        context=RequestContext(
            tenant_id=context.tenant_id, user_id=context.user_id, role=context.role
        ),
        access_token=issued.access_token,
        expires_at=identity.expires_at,
        refresh_token=issued.refresh_token,
    )


async def _sign_in_user(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    email: str,
    jit: bool,
    role: str | None,
    method: str,
) -> tuple[UUID | None, str | None]:
    """Find, or provision just in time, the tenant's user; record the sign-in."""
    async with tenant_session(factory, tenant_id) as session:
        user = await session.scalar(
            select(User).where(User.tenant_id == tenant_id, User.email == email)
        )
    if user is None:
        # An address belongs to one tenant (findings A8): never a second user elsewhere.
        async with role_session(factory, AUTH_ROLE) as lookup:
            elsewhere = await lookup.scalar(select(User.id).where(User.email == email))
        if elsewhere is not None:
            return None, "email_in_other_tenant"
        if not jit:
            return None, "not_invited"
    elif user.status == "deactivated":
        return None, "user_inactive"

    async with tenant_session(factory, tenant_id) as session:
        if user is None:
            user_id = uuid.uuid4()
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email=email,
                    display_name=email.partition("@")[0],
                    role=role or "user",
                    status="active",
                    last_login_at=func.now(),
                    last_login_method=METHOD,
                )
            )
            await session.flush()
            await record(
                session,
                tenant_id=tenant_id,
                actor_user_id=user_id,
                event="auth.user_provisioned",
                metadata={
                    "method": method,
                    "before": {},
                    "after": {
                        "user_id": str(user_id),
                        "role": role or "user",
                        "status": "active",
                    },
                },
            )
            log("auth.user_provisioned", tenant_id=str(tenant_id), user_id=str(user_id))
        else:
            user_id = user.id
            values: dict[str, object] = {
                "status": "active",
                "last_login_at": func.now(),
                "last_login_method": METHOD,
            }
            if role is not None and role != user.role:
                values["role"] = role
                await record(
                    session,
                    tenant_id=tenant_id,
                    actor_user_id=user_id,
                    event="auth.role_from_sso",
                    metadata={
                        "method": method,
                        "before": {"user_id": str(user_id), "role": user.role},
                        "after": {"user_id": str(user_id), "role": role},
                    },
                )
            await session.execute(
                update(User).where(User.tenant_id == tenant_id, User.id == user_id).values(values)
            )
        await record(
            session,
            tenant_id=tenant_id,
            actor_user_id=user_id,
            event="auth.login",
            metadata={"method": method, "status": "ok"},
        )
    return user_id, None
