"""/api/v1/admin: the tenant admin pages (P1a-13; architecture §7.2).

Every route depends on ``require_tenant_admin`` (``app.api.deps``): a signed-in user
whose ``users.role`` is ``tenant_admin``; anyone else gets 403 before the route runs.
Routes act on the admin's own tenant only: every query runs in the request's
tenant-scoped transaction (RLS), so another tenant's user or workspace is not found,
and nothing here takes a tenant ID from the request.

- Users: list (with last login and method), invite (as ``invited``; provisioned in
  Authentik like the operator's first admin, findings A15), change role, deactivate and
  reactivate. An admin cannot change their own role or status, so a tenant cannot lose
  its last admin through these routes. P1c-07: resend the invitation of a user still
  ``invited`` (one ``send_mail`` job), and remove a user: their account data and history
  are deleted (``app.tenancy.user_removal``), the audit events stay; never the admin
  themselves or the tenant's last admin.
- Workspace defaults: mode, model and reasoning among the tenant's enabled options. The
  additional instructions keep their routes (``PUT /workspaces/{id}/prompt``, findings
  B5): each save is a new version, with no revert in Phase 1a.
- Login policy (P1b-07): the tenant's sign-in methods and SSO source, read-only.
- Retention: shorten chat-history retention to between 1 and 30 days
  (``app.tenancy.retention``); never above 30 (CLAUDE.md).
- Usage (P2A-05): questions per day by mode, active users per day, the most cited
  sources and, with external models, month-to-date cost per model; counts only
  (``app.usage.dashboard``).
- Audit log (architecture §7.2, P1b-10): a CSV download of the tenant's sign-in, admin,
  operator, consent and download events (``EXPORTED_EVENTS``), metadata only as recorded
  (owner decision 18, Oct 22, 2026, for downloads). Query and feedback events and the
  operator-only tenant-name flags are not in it.

Every route is also behind the consent gate (``app.consent.gate``, P1b-10).

Every change writes an audit event with the values before and after.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, require_tenant_admin
from app.api.policy import policy_out
from app.api.schemas import (
    AdminUserOut,
    InvitationResentOut,
    LoginPolicyOut,
    RetentionIn,
    TenantSettingsOut,
    UsageOut,
    UserChangeIn,
    UserInviteIn,
    WorkspaceDefaultsIn,
    WorkspaceOut,
)
from app.audit.models import AuditEvent
from app.audit.writer import Change, record
from app.auth.links import normalise_email
from app.auth.provider import ProviderError, SignInLinkProvider
from app.chat.selection import load_entitlement
from app.consent.gate import active_version, require_consent
from app.core import cache
from app.core.db import APP_ROLE, AUTH_ROLE, role_session
from app.core.logging import log
from app.llm.catalogue import ModelChoice
from app.mail.queue import enqueue_invitation
from app.tenancy.context import RequestContext
from app.tenancy.entitlements import ModelRefused, check_choice
from app.tenancy.login_policy import TenantLoginPolicy
from app.tenancy.models import MAX_RETENTION_DAYS, Tenant, TenantEntitlements, User
from app.tenancy.retention import retention_days, set_retention
from app.tenancy.user_removal import RemovalRefused, remove_user
from app.tenancy.workspaces import Workspace
from app.usage.dashboard import tenant_usage

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")


# P1b-10: tenant admin pages are gated like conversations, after the role check.
router = APIRouter(
    prefix="/api/v1/admin",
    dependencies=[Depends(require_tenant_admin), Depends(require_consent)],
)


def _unprocessable(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=code)


def _user_values(user: User) -> Change:
    return {"user_id": str(user.id), "role": user.role, "status": user.status}


# --- users ----------------------------------------------------------------------------


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(
    request: Request, session: AsyncSession = Depends(db_session)
) -> list[AdminUserOut]:
    """The tenant's users, with the notice version each accepted (P2A-06)."""
    rows = await session.scalars(select(User).order_by(User.display_name, User.email))
    active = active_version(request)
    return [AdminUserOut.of(user, active) for user in rows]


@router.post("/users", status_code=status.HTTP_201_CREATED, response_model=AdminUserOut)
async def invite_user(
    body: UserInviteIn,
    request: Request,
    admin: RequestContext = Depends(require_tenant_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminUserOut:
    """Invite a user of one of the tenant's verified email domains, as ``invited``.

    The worker emails them an invitation (P1b-11); they then sign in from their own
    browser, and the first sign-in makes them ``active`` (findings A15). An email that
    exists in any tenant is refused: Authentik's usernames are emails, and an email maps
    to one tenant (findings A8).
    """
    email = normalise_email(body.email)
    if email is None:
        raise _unprocessable("invalid_email")
    tenant = await session.get(Tenant, admin.tenant_id)
    if tenant is None:
        raise NOT_FOUND
    if email.partition("@")[2] not in tenant.verified_domains:
        raise _unprocessable("domain_not_verified")
    # Across tenants, as the pre-authentication role (email and status only).
    async with role_session(request.app.state.db_factory, AUTH_ROLE) as lookup:
        if await lookup.scalar(select(User.id).where(User.email == email)) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="email_taken")
    provider: SignInLinkProvider | None = getattr(request.app.state, "sign_in_provider", None)
    if provider is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="no_identity_provider")
    user = User(
        id=uuid.uuid4(),
        tenant_id=admin.tenant_id,
        email=email,
        display_name=body.display_name.strip(),
        role=body.role,
        status="invited",
    )
    session.add(user)
    await session.flush()
    try:
        await provider.provision_user(
            email=email, display_name=user.display_name, tenant_id=admin.tenant_id
        )
        if body.role == "tenant_admin" and await _admin_mfa_required(session, admin.tenant_id):
            await provider.set_admin_mfa(email, True)  # P1b-08
    except ProviderError as exc:
        # The transaction rolls back: no users row without its Authentik user.
        log("tenant_admin.invite_failed", tenant_id=str(admin.tenant_id), error_code=exc.error_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="provisioning_failed") from None
    await session.refresh(user)
    # P1b-11: the invitation email, sent by the worker; commits with the user.
    await enqueue_invitation(
        session, tenant_id=admin.tenant_id, user_id=user.id, created_by=admin.user_id
    )
    await record(
        session,
        tenant_id=admin.tenant_id,
        actor_user_id=admin.user_id,
        event="tenant_admin.user_invited",
        metadata={"before": {}, "after": _user_values(user)},
    )
    log("tenant_admin.user_invited", tenant_id=str(admin.tenant_id), user_id=str(user.id))
    out = AdminUserOut.of(user, active_version(request))
    await session.commit()
    return out


async def _admin_mfa_required(session: AsyncSession, tenant_id: UUID) -> bool:
    # Explicit tenant predicate on top of RLS (review of Oct 22, 2026).
    required = await session.scalar(
        select(TenantLoginPolicy.admin_mfa_required).where(TenantLoginPolicy.tenant_id == tenant_id)
    )
    return required is not False  # no row: the default, required


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def change_user(
    user_id: UUID,
    body: UserChangeIn,
    request: Request,
    admin: RequestContext = Depends(require_tenant_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminUserOut:
    """Change role or status. Deactivated users are refused at sign-in and on every
    request; reactivating returns them to ``active``, or ``invited`` if they never
    signed in."""
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise NOT_FOUND
    if user.id == admin.user_id:
        raise _unprocessable("cannot_change_self")
    before = _user_values(user)
    if body.role is not None and body.role != user.role:
        # P1b-08: an admin's sign-in links ask for a second factor; a user's do not.
        provider: SignInLinkProvider | None = getattr(request.app.state, "sign_in_provider", None)
        if provider is not None:
            required = body.role == "tenant_admin" and await _admin_mfa_required(
                session, admin.tenant_id
            )
            try:
                await provider.set_admin_mfa(user.email, required)
            except ProviderError as exc:
                log(
                    "tenant_admin.mfa_sync_failed",
                    tenant_id=str(admin.tenant_id),
                    error_code=exc.error_code,
                )
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="mfa_not_updated") from None
        user.role = body.role
    if body.status == "deactivated":
        user.status = "deactivated"
    elif body.status == "active" and user.status == "deactivated":
        user.status = "active" if user.last_login_at is not None else "invited"
    await session.flush()
    after = _user_values(user)
    if after != before:
        await record(
            session,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.user_id,
            event="tenant_admin.user_changed",
            metadata={"before": before, "after": after},
        )
        log("tenant_admin.user_changed", tenant_id=str(admin.tenant_id), user_id=str(user.id))
    out = AdminUserOut.of(user, active_version(request))
    await session.commit()
    return out


@router.post(
    "/users/{user_id}/invitation",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InvitationResentOut,
)
async def resend_invitation(
    user_id: UUID,
    admin: RequestContext = Depends(require_tenant_admin),
    session: AsyncSession = Depends(db_session),
) -> InvitationResentOut:
    """P1c-07: queue the invitation email again for a user who has not signed in yet."""
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise NOT_FOUND
    if user.status != "invited":
        raise _unprocessable("not_invited")
    job_id = await enqueue_invitation(
        session, tenant_id=admin.tenant_id, user_id=user.id, created_by=admin.user_id
    )
    await record(
        session,
        tenant_id=admin.tenant_id,
        actor_user_id=admin.user_id,
        event="tenant_admin.invitation_resent",
        metadata={"job_id": str(job_id), "before": _user_values(user), "after": _user_values(user)},
    )
    log("tenant_admin.invitation_resent", tenant_id=str(admin.tenant_id), user_id=str(user.id))
    await session.commit()
    return InvitationResentOut(user_id=user.id, status="queued")


async def disable_provider_user(request: Request, email: str, tenant_id: UUID) -> None:
    """The removed user's Authentik account is deactivated with the removal (P1c-07); a
    provider failure rolls the removal back, like a failed invite."""
    provider: SignInLinkProvider | None = getattr(request.app.state, "sign_in_provider", None)
    if provider is None:
        return  # Phase 0 mode: no identity provider holds the user
    try:
        await provider.disable_user(email)
    except ProviderError as exc:
        log("user_removal.provider_failed", tenant_id=str(tenant_id), error_code=exc.error_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="provider_not_updated") from None


def removal_refused(exc: RemovalRefused) -> HTTPException:
    if exc.code == "not_found":
        return NOT_FOUND
    return _unprocessable(exc.code)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tenant_user(
    user_id: UUID,
    request: Request,
    admin: RequestContext = Depends(require_tenant_admin),
    session: AsyncSession = Depends(db_session),
) -> Response:
    """P1c-07: delete a user of the admin's tenant with their history; audited."""
    try:
        removed = await remove_user(
            session,
            tenant_id=admin.tenant_id,
            user_id=user_id,
            actor_user_id=admin.user_id,
            restore_role=APP_ROLE,
        )
    except RemovalRefused as exc:
        log("tenant_admin.remove_refused", tenant_id=str(admin.tenant_id), error_code=exc.code)
        raise removal_refused(exc) from None
    await disable_provider_user(request, removed.email, admin.tenant_id)
    await record(
        session,
        tenant_id=admin.tenant_id,
        actor_user_id=admin.user_id,
        event="tenant_admin.user_removed",
        metadata={
            "before": {"user_id": str(user_id), "role": removed.role, "status": removed.status},
            "after": {},
            "count": removed.total,
        },
    )
    log(
        "tenant_admin.user_removed",
        tenant_id=str(admin.tenant_id),
        user_id=str(user_id),
        count=removed.total,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- workspace defaults -----------------------------------------------------------------


def _defaults(workspace: Workspace) -> Change:
    return {
        "workspace_id": str(workspace.id),
        "default_mode": workspace.default_mode,
        "default_model": workspace.default_model,
        "default_reasoning": workspace.default_reasoning,
    }


@router.put("/workspaces/{workspace_id}/defaults", response_model=WorkspaceOut)
async def set_workspace_defaults(
    workspace_id: UUID,
    body: WorkspaceDefaultsIn,
    request: Request,
    admin: RequestContext = Depends(require_tenant_admin),
    session: AsyncSession = Depends(db_session),
) -> WorkspaceOut:
    """Default mode, model and reasoning of a new conversation in the workspace, among
    the modes and models the operator enabled for the tenant (P1a-03, P1a-09)."""
    workspace = await session.scalar(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    )
    if workspace is None:
        raise NOT_FOUND
    entitlements = await session.get(TenantEntitlements, admin.tenant_id)
    if entitlements is None or body.default_mode not in entitlements.answer_modes:
        raise _unprocessable("mode_not_enabled")
    try:
        check_choice(
            request.app.state.settings,
            await load_entitlement(session, admin.tenant_id),
            ModelChoice(body.default_model, body.default_reasoning),
        )
    except ModelRefused as exc:
        raise _unprocessable(exc.code) from None
    before = _defaults(workspace)
    workspace.default_mode = body.default_mode
    workspace.default_model = body.default_model
    workspace.default_reasoning = body.default_reasoning
    await session.flush()
    after = _defaults(workspace)
    if after != before:
        await record(
            session,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.user_id,
            event="tenant_admin.workspace_defaults_changed",
            metadata={"workspace_id": str(workspace.id), "before": before, "after": after},
        )
        log("tenant_admin.workspace_defaults_changed", tenant_id=str(admin.tenant_id))
    out = WorkspaceOut.model_validate(workspace)
    await session.commit()
    return out


# --- login policy (P1b-07): read-only ---------------------------------------------------


@router.get("/login-policy", response_model=LoginPolicyOut)
async def get_login_policy(
    request: Request,
    admin: RequestContext = Depends(require_tenant_admin),
    session: AsyncSession = Depends(db_session),
) -> LoginPolicyOut:
    """How the tenant's users sign in, as the operator configured it with the client's
    IT (architecture §7.4): shown, never changed here (self-service SSO is Phase 3)."""
    row = await session.get(TenantLoginPolicy, admin.tenant_id)
    if row is None:
        raise NOT_FOUND
    return policy_out(request, row)


# --- settings: retention --------------------------------------------------------------


async def _settings_out(session: AsyncSession, tenant_id: UUID) -> TenantSettingsOut:
    entitlements = await session.get(TenantEntitlements, tenant_id)
    return TenantSettingsOut(
        retention_days=await retention_days(session),
        max_retention_days=MAX_RETENTION_DAYS,
        answer_modes=list(entitlements.answer_modes) if entitlements else ["corpus_only"],
    )


# Event name prefixes (ending in ".") and exact names in the tenant admin's export.
EXPORTED_EVENTS: Final[tuple[str, ...]] = (
    "auth.",
    "tenant_admin.",
    "operator.",
    "consent.",
    "download",
    "download.refused",
    "workspace.prompt_saved",
)
MAX_EXPORT_ROWS: Final = 10_000
DEFAULT_EXPORT_DAYS: Final = 90
EXPORT_COLUMNS: Final = ("created_at", "event", "actor_user_id", "metadata")


def _exported(column: Any) -> Any:
    return or_(
        *(
            column.startswith(name, autoescape=True) if name.endswith(".") else column == name
            for name in EXPORTED_EVENTS
        )
    )


@router.get(
    "/audit-log",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "the tenant's audit events"}},
)
async def export_audit_log(
    since: date | None = None,
    admin: RequestContext = Depends(require_tenant_admin),
    session: AsyncSession = Depends(db_session),
) -> Response:
    """The tenant's audit events since ``since`` (default 90 days), oldest first, as CSV."""
    start = since or (datetime.now(UTC).date() - timedelta(days=DEFAULT_EXPORT_DAYS))
    rows = (
        await session.execute(
            select(
                AuditEvent.created_at,
                AuditEvent.event,
                AuditEvent.actor_user_id,
                AuditEvent.metadata_,
            )
            .where(
                AuditEvent.tenant_id == admin.tenant_id,
                AuditEvent.created_at >= datetime.combine(start, time.min, UTC),
                _exported(AuditEvent.event),
            )
            .order_by(AuditEvent.created_at, AuditEvent.id)
            .limit(MAX_EXPORT_ROWS)
        )
    ).all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.created_at.isoformat(),
                row.event,
                "" if row.actor_user_id is None else str(row.actor_user_id),
                json.dumps(row.metadata_, sort_keys=True, default=str),
            ]
        )
    await record(
        session,
        tenant_id=admin.tenant_id,
        actor_user_id=admin.user_id,
        event="tenant_admin.audit_exported",
        metadata={"count": len(rows)},
    )
    log("tenant_admin.audit_exported", tenant_id=str(admin.tenant_id), count=len(rows))
    await session.commit()
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="audit-log.csv"',
            "Cache-Control": "no-store",
        },
    )


# --- usage (P2A-05) -----------------------------------------------------------------------


@router.get("/usage", response_model=UsageOut)
async def get_usage(
    request: Request,
    admin: RequestContext = Depends(require_tenant_admin),
    session: AsyncSession = Depends(db_session),
) -> UsageOut:
    """The tenant's usage over the last 30 days: counts only, no text or per-user figure."""
    return await tenant_usage(session, request.app.state.settings, admin.tenant_id)


@router.get("/settings", response_model=TenantSettingsOut)
async def get_settings(
    admin: RequestContext = Depends(require_tenant_admin),
    session: AsyncSession = Depends(db_session),
) -> TenantSettingsOut:
    return await _settings_out(session, admin.tenant_id)


@router.put("/settings/retention", response_model=TenantSettingsOut)
async def set_retention_days(
    body: RetentionIn,
    admin: RequestContext = Depends(require_tenant_admin),
    session: AsyncSession = Depends(db_session),
) -> TenantSettingsOut:
    """Shorten (or restore up to 30 days) the tenant's chat-history retention."""
    before = await retention_days(session)
    shortened = await set_retention(session, admin.tenant_id, body.retention_days)
    if body.retention_days == 0 and before != 0:
        # P1b-14: a tenant that keeps no history is served no answer cached before the
        # switch either (new answers are not cached while retention is 0).
        cleared = await cache.clear_tenant(admin.tenant_id)
        log("tenant_admin.cache_cleared", tenant_id=str(admin.tenant_id), count=cleared)
    if body.retention_days != before:
        await record(
            session,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.user_id,
            event="tenant_admin.retention_changed",
            metadata={
                "before": {"retention_days": before},
                "after": {"retention_days": body.retention_days},
                "count": shortened,
            },
        )
        log("tenant_admin.retention_changed", tenant_id=str(admin.tenant_id), count=shortened)
    out = await _settings_out(session, admin.tenant_id)
    await session.commit()
    return out
