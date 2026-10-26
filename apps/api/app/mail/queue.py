"""Enqueue platform mail (P1b-11): a ``send_mail`` job in the caller's transaction.

The payload names the template and the recipient by identifier only; the worker reads
the address and renders the template when it sends (``app.mail.jobs``). So an
invitation commits with the user it invites, and a notice with the notice, and a
rolled-back invite sends nothing.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.jobs import enqueue
from app.core.mailtemplates import OPERATOR_TEMPLATES

# Retries with backoff (1, 2, 4, 8 minutes) for timeouts, 429 and 5xx (app.core.mail).
MAIL_MAX_ATTEMPTS: Final = 5


async def enqueue_invitation(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, created_by: UUID | None
) -> UUID:
    """The invitation email for an ``invited`` user (operator or tenant admin invite)."""
    return await enqueue(
        session,
        "send_mail",
        {"template": "invitation", "tenant_id": str(tenant_id), "user_id": str(user_id)},
        created_by=created_by,
        max_attempts=MAIL_MAX_ATTEMPTS,
    )


async def enqueue_consent_notice(session: AsyncSession, *, tenant_id: UUID, user_id: UUID) -> UUID:
    """The consent notice email for a user who accepted an earlier notice version
    (P1b-10, ``app.consent.notices``)."""
    return await enqueue(
        session,
        "send_mail",
        {"template": "consent_notice", "tenant_id": str(tenant_id), "user_id": str(user_id)},
        created_by=None,
        max_attempts=MAIL_MAX_ATTEMPTS,
    )


async def enqueue_operator_notice(session: AsyncSession, *, template: str, notice_id: UUID) -> UUID:
    """An operator notice's email. The worker sends it to every operator: this job fans
    out into one job per operator when it runs."""
    if template not in OPERATOR_TEMPLATES:
        raise ValueError(f"not an operator template: {template}")
    return await enqueue(
        session,
        "send_mail",
        {"template": template, "notice_id": str(notice_id)},
        created_by=None,
        max_attempts=MAIL_MAX_ATTEMPTS,
    )
