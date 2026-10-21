"""Per-tenant login policy and tenant discovery by email domain (P1b-06).

Mirrors alembic revision 0020; the migration is authoritative.

The login page asks for an email address; ``discover`` maps its domain to the one
active tenant that has verified it (a domain belongs to one tenant, architecture
§4.3) and returns that tenant's allowed methods. It never looks at users, so it
answers the same for a known and an unknown address of the same domain, and an
unknown domain (or a malformed address, or a suspended tenant's domain) gets
``NEUTRAL``: exactly what a links-only tenant's domain gets. Nothing about a tenant
other than the one owning the domain can reach the answer.

The operator sets the policy (``app.api.operator``); the tenant admin sees it
read-only (``app.api.admin``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, cast

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import AUTH_ROLE, Base, role_session
from app.tenancy.models import Tenant

SsoKind = Literal["entra", "google", "oidc", "saml"]
SSO_KINDS: Final[tuple[SsoKind, ...]] = ("entra", "google", "oidc", "saml")
Method = Literal["sso", "sign_in_link"]


class TenantLoginPolicy(Base):
    """How a tenant's users sign in. One row per tenant (created with the tenant)."""

    __tablename__ = "tenant_login_policy"
    __table_args__ = (
        CheckConstraint(
            "sso_source_kind IN ('none', 'entra', 'google', 'oidc', 'saml')",
            name="sso_kind_valid",
        ),
        CheckConstraint(
            "(sso_source_kind = 'none') = (sso_source_slug IS NULL)", name="sso_slug_with_kind"
        ),
        CheckConstraint("sso_source_slug ~ '^[a-z0-9][a-z0-9-]{1,70}$'", name="sso_slug_format"),
        CheckConstraint("jsonb_typeof(sso_source_config) = 'object'", name="sso_config_object"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    sign_in_links_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sso_source_kind: Mapped[str] = mapped_column(Text, server_default=text("'none'"))
    # The Authentik source's slug (P1b-07); set exactly when a kind is.
    sso_source_slug: Mapped[str | None] = mapped_column(Text, unique=True)
    # Non-secret fields only: secrets and SAML keys live in Authentik.
    sso_source_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    jit_provisioning_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    admin_mfa_required: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def sso_kind(self) -> SsoKind | None:
        kind = self.sso_source_kind
        return kind if kind in SSO_KINDS else None


@dataclass(frozen=True)
class Discovery:
    """What the login page may offer for an address. ``tenant_id`` stays server-side."""

    methods: tuple[Method, ...]
    sso_kind: SsoKind | None = None
    tenant_id: uuid.UUID | None = None
    sso_source_slug: str | None = None

    def public(self) -> tuple[tuple[Method, ...], SsoKind | None]:
        """The part the browser sees: the methods, and which kind of SSO button."""
        return self.methods, self.sso_kind


# Unknown domain, unknown user, malformed address and a links-only tenant look alike.
NEUTRAL: Final = Discovery(methods=("sign_in_link",))


def email_domain(email: str) -> str | None:
    local, at, domain = email.strip().lower().rpartition("@")
    if not at or not local or "." not in domain or len(domain) > 253:
        return None
    return domain


async def discover(factory: async_sessionmaker[AsyncSession], email: str) -> Discovery:
    """The methods ``email``'s domain allows, from its tenant's policy; else ``NEUTRAL``."""
    domain = email_domain(email)
    if domain is None:
        return NEUTRAL
    async with role_session(factory, AUTH_ROLE) as session:
        rows = (
            await session.execute(
                select(
                    TenantLoginPolicy.tenant_id,
                    TenantLoginPolicy.sign_in_links_enabled,
                    TenantLoginPolicy.sso_source_kind,
                    TenantLoginPolicy.sso_source_slug,
                )
                .join(Tenant, Tenant.id == TenantLoginPolicy.tenant_id)
                .where(Tenant.verified_domains.contains([domain]), Tenant.status == "active")
            )
        ).all()
    if len(rows) != 1:
        # No tenant, or (never by construction) two: offer nothing tenant-specific.
        return NEUTRAL
    row = rows[0]
    if row.sso_source_kind not in SSO_KINDS:
        # Links only, or links off and no SSO: the neutral answer either way. A link
        # request is then refused without saying why (app.auth.links).
        return NEUTRAL
    methods: tuple[Method, ...] = ("sso", "sign_in_link") if row.sign_in_links_enabled else ("sso",)
    return Discovery(
        methods=methods,
        sso_kind=cast(SsoKind, row.sso_source_kind),
        tenant_id=row.tenant_id,
        sso_source_slug=row.sso_source_slug,
    )
