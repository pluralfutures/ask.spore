"""The use and privacy notice and its acceptance (P1b-10).

``GET /api/v1/consent`` returns the active notice (``config/consent/<version>.md``) with
the user's accepted version; ``POST /api/v1/consent`` records the acceptance of the
active version on the user's row (``consent_version``, ``consented_at``) and in the
audit log (``consent.accepted``, with the version), in one transaction. Accepting a
version that is no longer the active one is refused (409 ``consent_version_stale``): the
user accepts only what they were shown. This router is not behind the consent gate
(``app.consent.gate``); every other user and tenant admin route is.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_tenant_id, current_user_id, db_session
from app.api.schemas import ConsentAcceptIn, ConsentNoticeOut
from app.audit.writer import record
from app.consent.gate import active_version
from app.consent.notice import ConsentNotice, load_notice
from app.core.config import Settings
from app.core.logging import log
from app.tenancy.models import User

router = APIRouter(prefix="/api/v1")

STALE = HTTPException(status.HTTP_409_CONFLICT, detail="consent_version_stale")


@lru_cache(maxsize=8)
def _notice(config_dir: Path, version: str) -> ConsentNotice:
    return load_notice(config_dir, version)  # checked at startup; released files never change


def _active_notice(request: Request) -> ConsentNotice:
    settings: Settings = request.app.state.settings
    return _notice(settings.config_dir, active_version(request))


async def _out(request: Request, session: AsyncSession) -> ConsentNoticeOut:
    notice = _active_notice(request)
    row = (
        await session.execute(
            select(User.consent_version, User.consented_at).where(
                User.id == current_user_id(request)
            )
        )
    ).one()
    return ConsentNoticeOut(
        version=notice.version,
        title=notice.title,
        summary=notice.summary,
        text=notice.text,
        accepted_version=row.consent_version,
        accepted_at=row.consented_at,
        required=row.consent_version != notice.version,
    )


@router.get("/consent", response_model=ConsentNoticeOut)
async def get_consent(
    request: Request, session: AsyncSession = Depends(db_session)
) -> ConsentNoticeOut:
    """The active notice in full, its summary, and what the user has accepted."""
    return await _out(request, session)


@router.post("/consent", response_model=ConsentNoticeOut)
async def accept_consent(
    body: ConsentAcceptIn, request: Request, session: AsyncSession = Depends(db_session)
) -> ConsentNoticeOut:
    """Accept the active notice version (idempotent: a second acceptance records nothing)."""
    tenant_id, user_id = current_tenant_id(request), current_user_id(request)
    if body.version != active_version(request):
        log(
            "consent.refused",
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            error_code="consent_version_stale",
        )
        raise STALE
    accepted = await session.scalar(
        update(User)
        .where(
            User.id == user_id,
            User.consent_version.is_distinct_from(body.version),
        )
        .values(consent_version=body.version, consented_at=func.now())
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    if accepted is not None:
        await record(
            session,
            tenant_id=tenant_id,
            actor_user_id=user_id,
            event="consent.accepted",
            metadata={"version": body.version},
        )
        log(
            "consent.accepted",
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            consent_version=body.version,
        )
    return await _out(request, session)
