"""The worker's ``send_mail`` job (P1b-11).

A job's payload names a template and its recipient by identifier (``app.mail.queue``):

- ``invitation`` and ``consent_notice``: ``tenant_id`` and ``user_id``. The address is
  read in that tenant's scope (RLS), and only while the user is still ``invited``
  (invitation) or ``active`` (consent notice); otherwise the job ends with
  ``recipient_gone`` and nothing is sent.
- operator templates (``spend_cap_80``, ``spend_cap_100``, ``tenant_name_flag``):
  ``notice_id`` alone first; that job adds one job per operator (``user_id``) and ends,
  so a retry resends to nobody who already had it. The address is read as
  ``askspore_operator``.

The worker renders the template at send time with the recipient's own address and the
app URL only, plus, for the invitation, the recipient's own first name
(``app.core.mailtemplates``) and sends it with ``app.core.mail``. A sent
email is audited under the recipient's tenant (``mail.sent``: template, version, job,
provider). The outcome is an error code and whether to retry, which the worker records
on the job; nothing here logs, and no address, subject or body reaches a log line, the
job row or the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.content.jobs import ClaimedJob, enqueue
from app.core.config import MailConfig
from app.core.db import OPERATOR_ROLE, role_session, tenant_session
from app.core.mail import MailError, MailSender
from app.core.mailtemplates import (
    OPERATOR_TEMPLATES,
    TEMPLATE_NAMES,
    MailTemplateError,
    load_template,
    render,
)
from app.mail.queue import MAIL_MAX_ATTEMPTS
from app.operator.models import Operator
from app.tenancy.models import INTERNAL_TENANT_ID, User

# Who a tenant template may still go to.
RECIPIENT_STATUS = {"invitation": "invited", "consent_notice": "active"}


@dataclass(frozen=True)
class MailContext:
    factory: async_sessionmaker[AsyncSession]
    config: MailConfig | None
    config_dir: Path
    sender: MailSender | None  # None without the active provider's key


@dataclass(frozen=True)
class MailOutcome:
    error_code: str | None = None
    retry: bool = False


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


async def _tenant_user(
    factory: async_sessionmaker[AsyncSession], tenant_id: UUID, user_id: UUID, status: str
) -> tuple[str, str] | None:
    """The recipient's address and display name."""
    async with tenant_session(factory, tenant_id) as session:
        row = (
            await session.execute(
                select(User.email, User.display_name).where(
                    User.tenant_id == tenant_id, User.id == user_id, User.status == status
                )
            )
        ).first()
        return None if row is None else (row.email, row.display_name)


async def _operator_email(factory: async_sessionmaker[AsyncSession], user_id: UUID) -> str | None:
    async with role_session(factory, OPERATOR_ROLE) as session:
        email: str | None = await session.scalar(
            select(User.email)
            .join(Operator, (Operator.tenant_id == User.tenant_id) & (Operator.user_id == User.id))
            .where(User.id == user_id, User.status != "deactivated")
        )
        return email


async def _fan_out(factory: async_sessionmaker[AsyncSession], template: str, notice: str) -> int:
    """One job per operator for this notice; returns how many."""
    async with role_session(factory, OPERATOR_ROLE) as session:
        operators = list(
            await session.scalars(
                select(Operator.user_id)
                .join(User, (User.tenant_id == Operator.tenant_id) & (User.id == Operator.user_id))
                .where(User.status != "deactivated")
                .order_by(Operator.granted_at)
            )
        )
        for user_id in operators:
            await enqueue(
                session,
                "send_mail",
                {"template": template, "notice_id": notice, "user_id": str(user_id)},
                created_by=None,
                max_attempts=MAIL_MAX_ATTEMPTS,
            )
    return len(operators)


async def send_mail(ctx: MailContext, job: ClaimedJob) -> MailOutcome:
    payload = job.payload
    template = payload.get("template")
    if template not in TEMPLATE_NAMES:
        return MailOutcome("bad_payload")
    user_id = _uuid(payload.get("user_id"))
    display_name: str | None = None
    if template in OPERATOR_TEMPLATES:
        notice = _uuid(payload.get("notice_id"))
        if notice is None:
            return MailOutcome("bad_payload")
        if user_id is None:
            await _fan_out(ctx.factory, str(template), str(notice))
            return MailOutcome()
        audit_tenant = INTERNAL_TENANT_ID
        email = await _operator_email(ctx.factory, user_id)
    else:
        tenant_id = _uuid(payload.get("tenant_id"))
        if tenant_id is None or user_id is None:
            return MailOutcome("bad_payload")
        audit_tenant = tenant_id
        recipient = await _tenant_user(
            ctx.factory, tenant_id, user_id, RECIPIENT_STATUS[str(template)]
        )
        email, display_name = recipient if recipient is not None else (None, None)
    if email is None:
        return MailOutcome("recipient_gone")
    if ctx.sender is None or ctx.config is None:
        return MailOutcome("mail_not_configured")
    version: str = getattr(ctx.config.templates, str(template))
    try:
        loaded = load_template(ctx.config_dir, str(template), version)
    except MailTemplateError:
        return MailOutcome("template_error")
    mail = render(
        loaded,
        recipient_email=email,
        app_url=ctx.config.app_url,
        recipient_display_name=display_name,
    )
    try:
        await ctx.sender.send(email, mail)
    except MailError as exc:
        return MailOutcome(exc.error_code, retry=exc.retryable)
    async with tenant_session(ctx.factory, audit_tenant) as session:
        await record(
            session,
            tenant_id=audit_tenant,
            actor_user_id=None,
            event="mail.sent",
            metadata={
                "template": str(template),
                "version": version,
                "job_id": str(job.id),
                "provider": ctx.sender.provider,
            },
        )
    return MailOutcome()
