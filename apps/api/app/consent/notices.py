"""The consent-notice email when the notice version changes (P1b-10).

When ``[consent] version`` moves on, every active user who accepted an earlier version
gets one ``consent_notice`` email (``config/mail/consent_notice``) through a
``send_mail`` job; the gate re-prompts them at their next request. Users who never
accepted are not mailed: the gate shows them the notice at their first sign-in.
``users.consent_notice_version`` records the version a notice was queued for, in the
same transaction as the job, so each user gets one email per version change however
often this runs. The worker runs it from its tick, at most once a minute.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import OPERATOR_ROLE, role_session, tenant_session
from app.core.logging import log
from app.mail.queue import enqueue_consent_notice
from app.tenancy.models import Tenant, User

CHECK_INTERVAL_SECONDS: Final = 60.0


async def queue_consent_notices(factory: async_sessionmaker[AsyncSession], version: str) -> int:
    """Queue the consent notice for every user still on an earlier accepted version;
    returns how many were queued."""
    async with role_session(factory, OPERATOR_ROLE) as session:
        tenant_ids: list[UUID] = list(await session.scalars(select(Tenant.id)))
    queued = 0
    for tenant_id in tenant_ids:
        async with tenant_session(factory, tenant_id) as session:
            user_ids = list(
                await session.scalars(
                    update(User)
                    .where(
                        User.tenant_id == tenant_id,
                        User.status == "active",
                        User.consent_version.is_not(None),
                        User.consent_version != version,
                        User.consent_notice_version.is_distinct_from(version),
                    )
                    .values(consent_notice_version=version)
                    .returning(User.id)
                    .execution_options(synchronize_session=False)
                )
            )
            for user_id in user_ids:
                await enqueue_consent_notice(session, tenant_id=tenant_id, user_id=user_id)
        if user_ids:
            log("consent.notices_queued", tenant_id=str(tenant_id), count=len(user_ids))
        queued += len(user_ids)
    return queued


class ConsentNoticeTick:
    """The worker tick: ``queue_consent_notices`` at most every ``interval`` seconds."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        version: str,
        *,
        interval: float = CHECK_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._factory = factory
        self._version = version
        self._interval = interval
        self._clock = clock
        self._last: float | None = None

    async def __call__(self) -> int:
        now = self._clock()
        if self._last is not None and now - self._last < self._interval:
            return 0
        self._last = now
        return await queue_consent_notices(self._factory, self._version)
