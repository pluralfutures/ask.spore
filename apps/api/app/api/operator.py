"""/api/v1/operator: the operator console (P1a-03; one tenant per page, P1b-12).

Every route depends on ``require_operator`` (``app.operator.deps``), never on a
tenant role, and runs as ``askspore_operator`` outside tenant RLS. The tenant a
route acts on is named in the path, which is the operator's to choose; nothing here
reads conversations, messages or the corpus (the role has no privileges on them).

P1b-12: the console shows one tenant per page. Its routes are the tenant's (by ID in
the path): the tenant, its entitlements (a save names the page's tenant, which must be
the path's, Phase 1a findings F2), login policy, workspaces with the tags offered to
that tenant only (its own and shared ones; another tenant's tags are refused), users,
and month-to-date spend and token usage by model from ``usage_ledger``. P1c-07: a
user still ``invited`` can be sent the invitation again, and any tenant's user can be
removed (``app.tenancy.user_removal``), as the tenant admin can for their own tenant. Cross-tenant
totals are on their own route and name no tenant. No route returns query text: the
role cannot read conversations or messages, and the ledger holds counts and cost only.

Every change writes an ``audit_events`` row under the affected tenant, with the
operator's user ID and the setting values before and after. Enabling external models
needs the client's acceptance (DPA document and date), stored on the entitlement row
and carried by the audit event; the database refuses the switch without it too.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import disable_provider_user, removal_refused
from app.api.policy import policy_out
from app.api.schemas import (
    AdminInvitedOut,
    AdminInviteIn,
    AdminUserOut,
    AggregateModelOut,
    AggregatesOut,
    EntitlementsIn,
    EntitlementsOut,
    EntraSourceIn,
    GoogleSourceIn,
    InvitationResentOut,
    LoginPolicyIn,
    LoginPolicyOut,
    ModelSpendOut,
    NoticeOut,
    OidcSourceIn,
    OperatorMeOut,
    OperatorOptionsOut,
    OperatorSourceOut,
    OperatorTagOut,
    OperatorWorkspaceOut,
    ProviderTotalOut,
    SourceDownloadableIn,
    SpendThresholdOut,
    SsoSourceIn,
    TenantCreateIn,
    TenantOut,
    TenantSpendOut,
    WorkspaceCreateIn,
    WorkspaceTagsIn,
)
from app.audit.writer import AuditValue, Change, record
from app.auth.links import normalise_email
from app.auth.provider import ProviderError, SignInLinkProvider, SourceAdmin
from app.auth.sources import (
    SourceRefused,
    config_digest,
    entra_config,
    google_config,
    oidc_config,
    parse_idp_metadata,
    saml_config,
    spec_for,
)
from app.content.models import Source
from app.content.store import STORABLE_TYPES
from app.content.tags import load_tags, tags_for_tenant
from app.core.db import OPERATOR_ROLE
from app.core.logging import log
from app.llm import catalogue
from app.mail.queue import enqueue_invitation
from app.operator.deps import OperatorContext, operator_session, require_operator
from app.operator.models import OperatorNotice
from app.tenancy.entitlements import available_answer_modes, available_models, default_model
from app.tenancy.login_policy import TenantLoginPolicy
from app.tenancy.models import INTERNAL_TENANT_ID, Tenant, TenantEntitlements, User
from app.tenancy.user_removal import RemovalRefused, remove_user
from app.tenancy.workspaces import Workspace
from app.usage.ledger import THRESHOLDS, month_of
from app.usage.models import SpendNotice, UsageLedger

router = APIRouter(prefix="/api/v1/operator", dependencies=[Depends(require_operator)])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
MAX_NOTICES = 200


def _unprocessable(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=code)


def _conflict(code: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=code)


def _tenant_values(tenant: Tenant) -> Change:
    return {
        "slug": tenant.slug,
        "display_name": tenant.display_name,
        "verified_domains": list(tenant.verified_domains),
        "status": tenant.status,
    }


def _entitlement_values(row: TenantEntitlements) -> Change:
    accepted = row.external_acceptance_date
    return {
        "answer_modes": list(row.answer_modes),
        "enabled_models": list(row.enabled_models),
        "external_models_enabled": row.external_models_enabled,
        "external_spend_cap_cents": row.external_spend_cap_cents,
        "external_acceptance_reference": row.external_acceptance_reference,
        "external_acceptance_date": accepted.isoformat() if accepted else None,
    }


def _policy_values(row: TenantLoginPolicy) -> Change:
    return {
        "sign_in_links_enabled": row.sign_in_links_enabled,
        "sso_source_kind": row.sso_source_kind,
        "sso_source_slug": row.sso_source_slug,
        "jit_provisioning_enabled": row.jit_provisioning_enabled,
        "admin_mfa_required": row.admin_mfa_required,
    }


async def _tenant_out(request: Request, session: AsyncSession, tenant: Tenant) -> TenantOut:
    entitlements = await session.get(TenantEntitlements, tenant.id)
    policy = await session.get(TenantLoginPolicy, tenant.id)
    if entitlements is None or policy is None:
        raise NOT_FOUND
    admins = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.tenant_id == tenant.id, User.role == "tenant_admin")
    )
    return TenantOut(
        id=tenant.id,
        slug=tenant.slug,
        display_name=tenant.display_name,
        verified_domains=list(tenant.verified_domains),
        status=tenant.status,
        created_at=tenant.created_at,
        admins=admins or 0,
        entitlements=EntitlementsOut.model_validate(entitlements),
        login_policy=policy_out(request, policy),
    )


@router.get("/me", response_model=OperatorMeOut)
async def operator_me(
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> OperatorMeOut:
    user = await session.get(User, operator.user_id)
    if user is None:
        raise NOT_FOUND
    return OperatorMeOut(email=user.email, display_name=user.display_name)


@router.get("/options", response_model=OperatorOptionsOut)
async def operator_options(request: Request) -> OperatorOptionsOut:
    settings = request.app.state.settings
    return OperatorOptionsOut(
        answer_modes=list(available_answer_modes()),
        models=list(available_models(settings)),
        tags=sorted(load_tags(settings.config_dir)),
    )


@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants(
    request: Request, session: AsyncSession = Depends(operator_session)
) -> list[TenantOut]:
    # A terminated tenant keeps its row (the audit log refers to it) but has no entitlements
    # or login policy (P1b-14); it is not listed, so it cannot hide the others (P1b-16 F5).
    tenants = (
        await session.scalars(
            select(Tenant)
            .join(TenantEntitlements, TenantEntitlements.tenant_id == Tenant.id)
            .join(TenantLoginPolicy, TenantLoginPolicy.tenant_id == Tenant.id)
            .order_by(Tenant.created_at)
        )
    ).all()
    return [await _tenant_out(request, session, tenant) for tenant in tenants]


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
async def get_tenant(
    tenant_id: UUID, request: Request, session: AsyncSession = Depends(operator_session)
) -> TenantOut:
    """One tenant, for its console page (P1b-12)."""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise NOT_FOUND
    return await _tenant_out(request, session, tenant)


@router.post("/tenants", status_code=status.HTTP_201_CREATED, response_model=TenantOut)
async def create_tenant(
    body: TenantCreateIn,
    request: Request,
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> TenantOut:
    if await session.scalar(select(Tenant.id).where(Tenant.slug == body.slug)):
        raise _conflict("slug_taken")
    # A domain belongs to one tenant (architecture §4.3).
    if body.verified_domains and await session.scalar(
        select(Tenant.id).where(Tenant.verified_domains.overlap(body.verified_domains))
    ):
        raise _conflict("domain_taken")
    tenant = Tenant(
        id=uuid.uuid4(),
        slug=body.slug,
        display_name=body.display_name.strip(),
        verified_domains=body.verified_domains,
        status="active",
    )
    entitlements = TenantEntitlements(
        tenant_id=tenant.id,
        answer_modes=["corpus_only"],
        enabled_models=[default_model(request.app.state.settings)],
        external_models_enabled=False,
    )
    session.add(tenant)
    try:
        await session.flush()
    except IntegrityError:
        raise _conflict("slug_taken") from None
    session.add(entitlements)
    await session.flush()
    await session.refresh(tenant)
    await session.refresh(entitlements)
    # Created with the tenant by a trigger (revision 0020): links on, no SSO.
    policy = await session.get(TenantLoginPolicy, tenant.id)
    if policy is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="no_login_policy")
    await record(
        session,
        tenant_id=tenant.id,
        actor_user_id=None,
        event="operator.tenant_created",
        metadata={
            "operator_id": str(operator.user_id),
            "before": {},
            "after": {
                **_tenant_values(tenant),
                **_entitlement_values(entitlements),
                **_policy_values(policy),
            },
        },
    )
    log("operator.tenant_created", tenant_id=str(tenant.id), user_id=str(operator.user_id))
    return await _tenant_out(request, session, tenant)


@router.post(
    "/tenants/{tenant_id}/admins",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminInvitedOut,
)
async def invite_admin(
    tenant_id: UUID,
    body: AdminInviteIn,
    request: Request,
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> AdminInvitedOut:
    """Create the tenant's admin as ``invited``, provision them in Authentik and queue
    their invitation email (P1b-11).

    They then sign in from their own browser; the first sign-in makes them ``active``.
    An email already used in any tenant is refused: Authentik's usernames are emails,
    and an email maps to one tenant (findings A8).
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise NOT_FOUND
    email = normalise_email(body.email)
    if email is None:
        raise _unprocessable("invalid_email")
    if await session.scalar(select(User.id).where(User.email == email)):
        raise _conflict("email_taken")
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email=email,
        display_name=body.display_name.strip(),
        role="tenant_admin",
        status="invited",
    )
    session.add(user)
    await session.flush()
    provider: SignInLinkProvider | None = getattr(request.app.state, "sign_in_provider", None)
    if provider is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="no_identity_provider")
    policy = await session.get(TenantLoginPolicy, tenant_id)
    try:
        await provider.provision_user(
            email=email, display_name=user.display_name, tenant_id=tenant_id
        )
        # P1b-08: Authentik asks the admin group for a second factor on sign-in links.
        if policy is None or policy.admin_mfa_required:
            await provider.set_admin_mfa(email, True)
    except ProviderError as exc:
        # The transaction rolls back: no users row without its Authentik user.
        log("operator.invite_failed", tenant_id=str(tenant_id), error_code=exc.error_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="provisioning_failed") from None
    # P1b-11: the invitation email, sent by the worker; commits with the user (A15).
    await enqueue_invitation(
        session, tenant_id=tenant_id, user_id=user.id, created_by=operator.user_id
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=None,
        event="operator.admin_invited",
        metadata={
            "operator_id": str(operator.user_id),
            "before": {},
            "after": {"user_id": str(user.id), "role": "tenant_admin", "status": "invited"},
        },
    )
    log("operator.admin_invited", tenant_id=str(tenant_id), user_id=str(user.id))
    return AdminInvitedOut(user_id=user.id, status="invited")


@router.put("/tenants/{tenant_id}/entitlements", response_model=EntitlementsOut)
async def set_entitlements(
    tenant_id: UUID,
    body: EntitlementsIn,
    request: Request,
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> TenantEntitlements:
    if body.tenant_id != tenant_id:
        # F2: a save made on one tenant's page never lands on another tenant.
        log("operator.entitlements_refused", tenant_id=str(tenant_id), error_code="mismatch")
        raise _conflict("tenant_mismatch")
    row = await session.get(TenantEntitlements, tenant_id, with_for_update=True)
    if row is None:
        raise NOT_FOUND
    if "corpus_only" not in body.answer_modes:
        raise _unprocessable("corpus_only_required")
    if set(body.enabled_models) - set(available_models(request.app.state.settings)):
        raise _unprocessable("unknown_model")
    acceptance = body.external_acceptance
    if body.external_models_enabled:
        if body.external_spend_cap_cents is None:
            raise _unprocessable("spend_cap_required")
        # Switching external models on needs the client's signed acceptance (P1a-03).
        if acceptance is None and not row.external_models_enabled:
            raise _unprocessable("acceptance_required")
    if acceptance is not None and acceptance.accepted_on > date.today():
        raise _unprocessable("acceptance_in_future")

    before = _entitlement_values(row)
    row.answer_modes = sorted(set(body.answer_modes))
    row.enabled_models = sorted(set(body.enabled_models))
    row.external_models_enabled = body.external_models_enabled
    row.external_spend_cap_cents = body.external_spend_cap_cents
    if acceptance is not None:
        row.external_acceptance_reference = acceptance.reference.strip()
        row.external_acceptance_date = acceptance.accepted_on
    row.updated_at = func.now()
    await session.flush()
    await session.refresh(row)
    after = _entitlement_values(row)
    if after != before:
        metadata: dict[str, AuditValue] = {
            "operator_id": str(operator.user_id),
            "before": before,
            "after": after,
        }
        if acceptance is not None:
            metadata["acceptance_reference"] = row.external_acceptance_reference
            metadata["acceptance_date"] = acceptance.accepted_on.isoformat()
        await record(
            session,
            tenant_id=tenant_id,
            actor_user_id=None,
            event="operator.entitlements_changed",
            metadata=metadata,
        )
        log("operator.entitlements_changed", tenant_id=str(tenant_id), status="changed")
    return row


# --- login policy (P1b-06) ----------------------------------------------------------------


@router.get("/tenants/{tenant_id}/login-policy", response_model=LoginPolicyOut)
async def get_login_policy(
    tenant_id: UUID, request: Request, session: AsyncSession = Depends(operator_session)
) -> LoginPolicyOut:
    row = await session.get(TenantLoginPolicy, tenant_id)
    if row is None:
        raise NOT_FOUND
    return policy_out(request, row)


@router.put("/tenants/{tenant_id}/login-policy", response_model=LoginPolicyOut)
async def set_login_policy(
    tenant_id: UUID,
    body: LoginPolicyIn,
    request: Request,
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> LoginPolicyOut:
    """Sign-in links on or off (on by default), JIT provisioning from the tenant's SSO
    source, and the MFA requirement for tenant admins. Audited with before and after."""
    row = await session.get(TenantLoginPolicy, tenant_id, with_for_update=True)
    if row is None:
        raise NOT_FOUND
    before = _policy_values(row)
    if body.admin_mfa_required != row.admin_mfa_required:
        # P1b-08: the tenant's admins join or leave the group Authentik's second factor is
        # bound to. Nothing is saved unless Authentik took every change.
        provider: SignInLinkProvider | None = getattr(request.app.state, "sign_in_provider", None)
        if provider is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="no_identity_provider")
        admins = await session.scalars(
            select(User.email).where(
                User.tenant_id == tenant_id,
                User.role == "tenant_admin",
                User.status != "deactivated",
            )
        )
        try:
            for email in admins:
                await provider.set_admin_mfa(email, body.admin_mfa_required)
        except ProviderError as exc:
            log("operator.mfa_sync_failed", tenant_id=str(tenant_id), error_code=exc.error_code)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="mfa_not_updated") from None
    row.sign_in_links_enabled = body.sign_in_links_enabled
    row.jit_provisioning_enabled = body.jit_provisioning_enabled
    row.admin_mfa_required = body.admin_mfa_required
    row.updated_at = func.now()
    await session.flush()
    await session.refresh(row)
    after = _policy_values(row)
    if after != before:
        await record(
            session,
            tenant_id=tenant_id,
            actor_user_id=None,
            event="operator.login_policy_changed",
            metadata={"operator_id": str(operator.user_id), "before": before, "after": after},
        )
        log("operator.login_policy_changed", tenant_id=str(tenant_id), status="changed")
    return policy_out(request, row)


# --- the tenant's SSO source (P1b-07) -----------------------------------------------------


def _sso_values(row: TenantLoginPolicy) -> Change:
    return {
        "sso_source_kind": row.sso_source_kind,
        "sso_source_slug": row.sso_source_slug,
        "sso_config_sha256": config_digest(row.sso_kind, row.sso_source_config),
    }


def _source_config(body: SsoSourceIn) -> tuple[dict[str, str | list[str]], str | None]:
    """The non-secret configuration to store, and the IdP's certificate (SAML)."""
    if isinstance(body, EntraSourceIn):
        return entra_config(body.entra_tenant_id, body.client_id, body.admin_group_ids), None
    if isinstance(body, GoogleSourceIn):
        return google_config(body.client_id), None
    if isinstance(body, OidcSourceIn):
        return oidc_config(body.issuer, body.client_id), None
    metadata = parse_idp_metadata(body.metadata_xml)
    return saml_config(metadata), metadata.certificate_pem


def _source_admin(request: Request) -> SourceAdmin:
    provider: SourceAdmin | None = getattr(request.app.state, "sign_in_provider", None)
    if provider is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="no_identity_provider")
    return provider


async def _audit_source(
    session: AsyncSession, tenant_id: UUID, operator: OperatorContext, before: Change, after: Change
) -> None:
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=None,
        event="operator.sso_source_changed",
        metadata={"operator_id": str(operator.user_id), "before": before, "after": after},
    )
    log("operator.sso_source_changed", tenant_id=str(tenant_id), status="changed")


@router.put("/tenants/{tenant_id}/login-policy/sso", response_model=LoginPolicyOut)
async def set_sso_source(
    tenant_id: UUID,
    body: SsoSourceIn,
    request: Request,
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> LoginPolicyOut:
    """Configure the tenant's one SSO source in Authentik and keep its non-secret fields.

    The client secret (OIDC kinds) goes to Authentik only. A new source, or a change of
    kind, needs it; otherwise omitting it keeps the one Authentik holds. Audited with
    the kind, the source slug and a fingerprint of the stored configuration.
    """
    tenant = await session.get(Tenant, tenant_id)
    row = await session.get(TenantLoginPolicy, tenant_id, with_for_update=True)
    if tenant is None or row is None:
        raise NOT_FOUND
    secret = getattr(body, "client_secret", None)
    if body.kind != "saml" and secret is None and row.sso_source_kind != body.kind:
        raise _unprocessable("client_secret_required")
    try:
        config, certificate = _source_config(body)
        spec = spec_for(
            tenant_id=tenant_id,
            tenant_slug=tenant.slug,
            verified_domains=list(tenant.verified_domains),
            kind=body.kind,
            config=config,
            certificate_pem=certificate,
        )
    except SourceRefused as exc:
        raise _unprocessable(exc.error_code) from None
    provider = _source_admin(request)
    try:
        await provider.configure_source(spec, secret)
    except ProviderError as exc:
        log("operator.sso_source_failed", tenant_id=str(tenant_id), error_code=exc.error_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="source_not_configured") from None
    before = _sso_values(row)
    row.sso_source_kind = body.kind
    row.sso_source_slug = spec.slug
    row.sso_source_config = config
    row.updated_at = func.now()
    await session.flush()
    await session.refresh(row)
    after = _sso_values(row)
    if after != before:
        await _audit_source(session, tenant_id, operator, before, after)
    return policy_out(request, row)


@router.delete("/tenants/{tenant_id}/login-policy/sso", response_model=LoginPolicyOut)
async def remove_sso_source(
    tenant_id: UUID,
    request: Request,
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> LoginPolicyOut:
    """Remove the tenant's source from Authentik; its users then sign in with links (if
    the policy allows them) until a source is configured again. Audited."""
    row = await session.get(TenantLoginPolicy, tenant_id, with_for_update=True)
    if row is None:
        raise NOT_FOUND
    kind, slug = row.sso_kind, row.sso_source_slug
    if kind is None or slug is None:
        return policy_out(request, row)
    try:
        await _source_admin(request).remove_source(kind, slug)
    except ProviderError as exc:
        log("operator.sso_source_failed", tenant_id=str(tenant_id), error_code=exc.error_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="source_not_removed") from None
    before = _sso_values(row)
    row.sso_source_kind = "none"
    row.sso_source_slug = None
    row.sso_source_config = {}
    row.updated_at = func.now()
    await session.flush()
    await session.refresh(row)
    await _audit_source(session, tenant_id, operator, before, _sso_values(row))
    return policy_out(request, row)


@router.get("/notices", response_model=list[NoticeOut])
async def list_notices(session: AsyncSession = Depends(operator_session)) -> list[NoticeOut]:
    rows = await session.execute(
        select(OperatorNotice, Tenant.slug)
        .join(Tenant, Tenant.id == OperatorNotice.tenant_id)
        .order_by(OperatorNotice.created_at.desc())
        .limit(MAX_NOTICES)
    )
    return [
        NoticeOut(
            id=notice.id,
            tenant_id=notice.tenant_id,
            tenant_slug=slug,
            kind=notice.kind,
            created_at=notice.created_at,
        )
        for notice, slug in rows
    ]


# --- package builder: workspaces and their tags (P1a-04) ---------------------------------


def _workspace_values(workspace: Workspace) -> Change:
    return {
        "workspace_id": str(workspace.id),
        "slug": workspace.slug,
        "name": workspace.name,
        "tag_ids": list(workspace.tag_ids),
        "default_mode": workspace.default_mode,
        "default_model": workspace.default_model,
        "default_reasoning": workspace.default_reasoning,
    }


async def _tenant_tags(request: Request, session: AsyncSession, tenant_id: UUID) -> list[str]:
    """The tags this tenant's workspaces may use: its own and the shared ones (P1b-12)."""
    slug = await session.scalar(select(Tenant.slug).where(Tenant.id == tenant_id))
    if slug is None:
        raise NOT_FOUND
    return tags_for_tenant(load_tags(request.app.state.settings.config_dir), slug)


async def _check_tags(
    request: Request, session: AsyncSession, tenant_id: UUID, tag_ids: list[str]
) -> list[str]:
    """Tags must exist in config/tags.toml and be the tenant's own or shared (P1b-12);
    tags may repeat across workspaces."""
    tags = load_tags(request.app.state.settings.config_dir)
    if set(tag_ids) - set(tags):
        raise _unprocessable("unknown_tag")
    if set(tag_ids) - set(await _tenant_tags(request, session, tenant_id)):
        raise _unprocessable("tag_not_for_tenant")
    return sorted(set(tag_ids))


@router.get("/tenants/{tenant_id}/tags", response_model=list[OperatorTagOut])
async def list_tenant_tags(
    tenant_id: UUID, request: Request, session: AsyncSession = Depends(operator_session)
) -> list[OperatorTagOut]:
    """What the tenant's workspace tag pickers offer (P1b-12)."""
    tags = load_tags(request.app.state.settings.config_dir)
    return [
        OperatorTagOut(tag=tag, shared=tags[tag].tenant is None)
        for tag in await _tenant_tags(request, session, tenant_id)
    ]


@router.get("/tenants/{tenant_id}/workspaces", response_model=list[OperatorWorkspaceOut])
async def list_workspaces(
    tenant_id: UUID, session: AsyncSession = Depends(operator_session)
) -> list[Workspace]:
    rows = await session.scalars(
        select(Workspace).where(Workspace.tenant_id == tenant_id).order_by(Workspace.slug)
    )
    return list(rows)


@router.post(
    "/tenants/{tenant_id}/workspaces",
    status_code=status.HTTP_201_CREATED,
    response_model=OperatorWorkspaceOut,
)
async def create_workspace(
    tenant_id: UUID,
    body: WorkspaceCreateIn,
    request: Request,
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> Workspace:
    entitlements = await session.get(TenantEntitlements, tenant_id)
    if entitlements is None:
        raise NOT_FOUND
    if body.default_mode not in entitlements.answer_modes:
        raise _unprocessable("mode_not_enabled")
    if body.default_model not in entitlements.enabled_models:
        raise _unprocessable("model_not_enabled")
    if await session.scalar(
        select(Workspace.id).where(Workspace.tenant_id == tenant_id, Workspace.slug == body.slug)
    ):
        raise _conflict("slug_taken")
    workspace = Workspace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        slug=body.slug,
        name=body.name.strip(),
        tag_ids=await _check_tags(request, session, tenant_id, body.tag_ids),
        default_mode=body.default_mode,
        default_model=body.default_model,
        default_reasoning=body.default_reasoning,
    )
    session.add(workspace)
    await session.flush()
    await session.refresh(workspace)
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=None,
        event="operator.workspace_created",
        metadata={
            "operator_id": str(operator.user_id),
            "before": {},
            "after": _workspace_values(workspace),
        },
    )
    log("operator.workspace_created", tenant_id=str(tenant_id), user_id=str(operator.user_id))
    return workspace


@router.put(
    "/tenants/{tenant_id}/workspaces/{workspace_id}/tags", response_model=OperatorWorkspaceOut
)
async def set_workspace_tags(
    tenant_id: UUID,
    workspace_id: UUID,
    body: WorkspaceTagsIn,
    request: Request,
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> Workspace:
    """Assign the workspace's tags (its corpus). Audited with before and after."""
    workspace = await session.scalar(
        select(Workspace)
        .where(Workspace.tenant_id == tenant_id, Workspace.id == workspace_id)
        .with_for_update()
    )
    if workspace is None:
        raise NOT_FOUND
    before = _workspace_values(workspace)
    workspace.tag_ids = await _check_tags(request, session, tenant_id, body.tag_ids)
    await session.flush()
    after = _workspace_values(workspace)
    if after != before:
        await record(
            session,
            tenant_id=tenant_id,
            actor_user_id=None,
            event="operator.workspace_tags_changed",
            metadata={"operator_id": str(operator.user_id), "before": before, "after": after},
        )
        log("operator.workspace_tags_changed", tenant_id=str(tenant_id), status="changed")
    return workspace


# --- users, spend and cross-tenant totals (P1b-12) ----------------------------------------


@router.get("/tenants/{tenant_id}/users", response_model=list[AdminUserOut])
async def list_tenant_users(
    tenant_id: UUID, session: AsyncSession = Depends(operator_session)
) -> list[User]:
    """The tenant's users, as its admin sees them (no conversation data)."""
    if await session.get(Tenant, tenant_id) is None:
        raise NOT_FOUND
    rows = await session.scalars(
        select(User).where(User.tenant_id == tenant_id).order_by(User.display_name, User.email)
    )
    return list(rows)


@router.post(
    "/tenants/{tenant_id}/users/{user_id}/invitation",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InvitationResentOut,
)
async def resend_invitation(
    tenant_id: UUID,
    user_id: UUID,
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> InvitationResentOut:
    """P1c-07: queue the invitation email again for a user still ``invited``."""
    user = await session.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    if user is None:
        raise NOT_FOUND
    if user.status != "invited":
        raise _unprocessable("not_invited")
    job_id = await enqueue_invitation(
        session, tenant_id=tenant_id, user_id=user.id, created_by=operator.user_id
    )
    values: Change = {"user_id": str(user.id), "role": user.role, "status": user.status}
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=None,
        event="operator.invitation_resent",
        metadata={
            "operator_id": str(operator.user_id),
            "job_id": str(job_id),
            "before": values,
            "after": values,
        },
    )
    log("operator.invitation_resent", tenant_id=str(tenant_id), user_id=str(user.id))
    return InvitationResentOut(user_id=user.id, status="queued")


@router.delete("/tenants/{tenant_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tenant_user(
    tenant_id: UUID,
    user_id: UUID,
    request: Request,
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> Response:
    """P1c-07: delete any tenant's user with their history; audited under the tenant."""
    if await session.get(Tenant, tenant_id) is None:
        raise NOT_FOUND
    try:
        removed = await remove_user(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            actor_user_id=operator.user_id,
            restore_role=OPERATOR_ROLE,
        )
    except RemovalRefused as exc:
        log("operator.remove_refused", tenant_id=str(tenant_id), error_code=exc.code)
        raise removal_refused(exc) from None
    await disable_provider_user(request, removed.email, tenant_id)
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=None,
        event="operator.user_removed",
        metadata={
            "operator_id": str(operator.user_id),
            "before": {"user_id": str(user_id), "role": removed.role, "status": removed.status},
            "after": {},
            "count": removed.total,
        },
    )
    log(
        "operator.user_removed",
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        count=removed.total,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _model_spend(request: Request, row: UsageLedger) -> ModelSpendOut:
    entry = catalogue.entry(request.app.state.settings, row.model)
    return ModelSpendOut(
        model=row.model,
        display_name=entry.display_name if entry else row.model,
        external=entry.external if entry else False,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        cost_cents=row.cost_cents,
    )


@router.get("/tenants/{tenant_id}/spend", response_model=TenantSpendOut)
async def tenant_spend(
    tenant_id: UUID, request: Request, session: AsyncSession = Depends(operator_session)
) -> TenantSpendOut:
    """Month-to-date token usage and cost by model, from ``usage_ledger``, and external
    spend against the cap with the 80 and 100 percent notice thresholds (UTC month)."""
    entitlements = await session.get(TenantEntitlements, tenant_id)
    if entitlements is None:
        raise NOT_FOUND
    month = month_of()
    rows = await session.scalars(
        select(UsageLedger)
        .where(UsageLedger.tenant_id == tenant_id, UsageLedger.month == month)
        .order_by(UsageLedger.model)
    )
    models = [_model_spend(request, row) for row in rows]
    spent = sum((m.cost_cents for m in models if m.external), Decimal(0))
    notified = {
        n.threshold: n.created_at
        for n in await session.scalars(
            select(SpendNotice).where(
                SpendNotice.tenant_id == tenant_id, SpendNotice.month == month
            )
        )
    }
    cap = entitlements.external_spend_cap_cents
    thresholds = (
        [
            SpendThresholdOut(
                percent=percent,
                cents=Decimal(cap) * percent / 100,
                reached=spent * 100 >= cap * percent,
                notified_at=notified.get(percent),
            )
            for percent in THRESHOLDS
        ]
        if cap is not None
        else []
    )
    return TenantSpendOut(
        tenant_id=tenant_id,
        month=month.strftime("%Y-%m"),
        models=models,
        external_spent_cents=spent,
        external_models_enabled=entitlements.external_models_enabled,
        external_spend_cap_cents=cap,
        thresholds=thresholds,
    )


@router.get("/aggregates", response_model=AggregatesOut)
async def aggregates(
    request: Request, session: AsyncSession = Depends(operator_session)
) -> AggregatesOut:
    """Cross-tenant totals for the month: per model and per provider, and how many
    tenants used each. No tenant is named; there is no query text to show."""
    settings = request.app.state.settings
    month = month_of()
    rows = (
        await session.execute(
            select(
                UsageLedger.model,
                func.count(func.distinct(UsageLedger.tenant_id)).label("tenants"),
                func.sum(UsageLedger.tokens_in).label("tokens_in"),
                func.sum(UsageLedger.tokens_out).label("tokens_out"),
                func.sum(UsageLedger.cost_cents).label("cost_cents"),
            )
            .where(UsageLedger.month == month)
            .group_by(UsageLedger.model)
            .order_by(UsageLedger.model)
        )
    ).all()
    models = []
    providers: dict[str, ProviderTotalOut] = {}
    for r in rows:
        entry = catalogue.entry(settings, r.model)
        provider = entry.provider if entry else "other"
        model = AggregateModelOut(
            model=r.model,
            display_name=entry.display_name if entry else r.model,
            external=entry.external if entry else False,
            provider=provider,
            tenants=r.tenants,
            tokens_in=int(r.tokens_in),
            tokens_out=int(r.tokens_out),
            cost_cents=Decimal(r.cost_cents),
        )
        models.append(model)
        total = providers.setdefault(
            provider,
            ProviderTotalOut(provider=provider, tokens_in=0, tokens_out=0, cost_cents=Decimal(0)),
        )
        total.tokens_in += model.tokens_in
        total.tokens_out += model.tokens_out
        total.cost_cents += model.cost_cents
    with_usage = await session.scalar(
        select(func.count(func.distinct(UsageLedger.tenant_id))).where(UsageLedger.month == month)
    )
    tenants = await session.scalar(select(func.count()).select_from(Tenant))
    return AggregatesOut(
        month=month.strftime("%Y-%m"),
        tenants=tenants or 0,
        tenants_with_usage=with_usage or 0,
        models=models,
        providers=sorted(providers.values(), key=lambda p: p.provider),
    )


# --- source register: the download switch (P1a-14) ---------------------------------------


@router.get("/sources", response_model=list[OperatorSourceOut])
async def list_sources(
    session: AsyncSession = Depends(operator_session),
) -> list[OperatorSourceOut]:
    """Every register row with its download switch. The operator role reads only these
    columns (revision 0012), never the RAGFlow document IDs."""
    rows = await session.execute(
        select(
            Source.id,
            Source.type,
            Source.title,
            Source.publisher,
            Source.tags,
            Source.status,
            Source.licence_basis,
            Source.downloadable,
            Source.stored_path,
        ).order_by(Source.publisher, Source.title, Source.id)
    )
    return [
        OperatorSourceOut(
            id=r.id,
            type=r.type,
            title=r.title,
            publisher=r.publisher,
            tags=list(r.tags),
            status=r.status,
            licence_basis=r.licence_basis,
            downloadable=r.downloadable,
            stored=r.stored_path is not None,
        )
        for r in rows
    ]


@router.put("/sources/{source_id}/downloadable", response_model=OperatorSourceOut)
async def set_source_downloadable(
    source_id: UUID,
    body: SourceDownloadableIn,
    operator: OperatorContext = Depends(require_operator),
    session: AsyncSession = Depends(operator_session),
) -> OperatorSourceOut:
    """Open or close the licence gate of one source, from its licence basis. Audited
    under the platform tenant (sources are shared corpus, not a tenant's)."""
    row = (
        await session.execute(
            select(Source.id, Source.type, Source.downloadable, Source.stored_path)
            .where(Source.id == source_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    if body.downloadable and row.type not in STORABLE_TYPES:
        raise _unprocessable("not_a_file")
    if body.downloadable and row.stored_path is None:
        raise _unprocessable("not_stored")
    if body.downloadable != row.downloadable:
        await session.execute(
            update(Source)
            .where(Source.id == source_id)
            .values(downloadable=body.downloadable, updated_at=func.now())
        )
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=None,
            event="operator.source_downloadable_changed",
            metadata={
                "operator_id": str(operator.user_id),
                "source_id": str(source_id),
                "before": {"downloadable": row.downloadable},
                "after": {"downloadable": body.downloadable},
            },
        )
        log("operator.source_downloadable_changed", source_id=str(source_id), status="changed")
    (out,) = [s for s in await list_sources(session) if s.id == source_id]
    return out
