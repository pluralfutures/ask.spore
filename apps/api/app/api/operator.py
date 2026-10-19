"""/api/v1/operator: the operator console, minimum (P1a-03).

Every route depends on ``require_operator`` (``app.operator.deps``), never on a
tenant role, and runs as ``askspore_operator`` outside tenant RLS. The tenant a
route acts on is named in the path, which is the operator's to choose; nothing here
reads conversations, messages or the corpus (the role has no privileges on them).

Every change writes an ``audit_events`` row under the affected tenant, with the
operator's user ID and the setting values before and after. Enabling external models
needs the client's acceptance (DPA document and date), stored on the entitlement row
and carried by the audit event; the database refuses the switch without it too.
"""

from __future__ import annotations

import uuid
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    AdminInvitedOut,
    AdminInviteIn,
    EntitlementsIn,
    EntitlementsOut,
    NoticeOut,
    OperatorMeOut,
    OperatorOptionsOut,
    TenantCreateIn,
    TenantOut,
)
from app.audit.writer import AuditValue, Change, record
from app.auth.links import normalise_email
from app.auth.provider import ProviderError, SignInLinkProvider
from app.core.logging import log
from app.operator.deps import OperatorContext, operator_session, require_operator
from app.operator.models import OperatorNotice
from app.tenancy.entitlements import available_answer_modes, available_models, default_model
from app.tenancy.models import Tenant, TenantEntitlements, User

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
        "sign_in_links_enabled": row.sign_in_links_enabled,
        "external_acceptance_reference": row.external_acceptance_reference,
        "external_acceptance_date": accepted.isoformat() if accepted else None,
    }


async def _tenant_out(session: AsyncSession, tenant: Tenant) -> TenantOut:
    entitlements = await session.get(TenantEntitlements, tenant.id)
    if entitlements is None:
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
    return OperatorOptionsOut(
        answer_modes=list(available_answer_modes()),
        models=list(available_models(request.app.state.settings)),
    )


@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants(session: AsyncSession = Depends(operator_session)) -> list[TenantOut]:
    tenants = (await session.scalars(select(Tenant).order_by(Tenant.created_at))).all()
    return [await _tenant_out(session, tenant) for tenant in tenants]


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
        sign_in_links_enabled=True,
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
    await record(
        session,
        tenant_id=tenant.id,
        actor_user_id=None,
        event="operator.tenant_created",
        metadata={
            "operator_id": str(operator.user_id),
            "before": {},
            "after": {**_tenant_values(tenant), **_entitlement_values(entitlements)},
        },
    )
    log("operator.tenant_created", tenant_id=str(tenant.id), user_id=str(operator.user_id))
    return await _tenant_out(session, tenant)


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
    """Create the tenant's admin as ``invited`` and provision them in Authentik.

    They then sign in with a link from their own browser; the first sign-in makes
    them ``active``. An email already used in any tenant is refused: Authentik's
    usernames are emails, and an email maps to one tenant (findings A8).
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
    try:
        await provider.provision_user(
            email=email, display_name=user.display_name, tenant_id=tenant_id
        )
    except ProviderError as exc:
        # The transaction rolls back: no users row without its Authentik user.
        log("operator.invite_failed", tenant_id=str(tenant_id), error_code=exc.error_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="provisioning_failed") from None
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
    row.sign_in_links_enabled = body.sign_in_links_enabled
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
