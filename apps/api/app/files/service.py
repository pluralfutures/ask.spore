"""Workspace file list and downloads (P1a-14; architecture §14.3).

The list shows the PDF, DOCX and PPTX sources in the workspace's tags, from the source
register, and rolls crawled pages up to their site with a page count. Which sources a
workspace holds is decided here from the workspace row (RLS: only the session tenant's
workspaces are visible), never from the request: the request names only our own
workspace and source-register UUIDs, and a source outside the workspace's tags is not
found, whether listed or asked for directly.

A file can be downloaded only when its register row is ``downloadable`` (the licence
gate) and our own copy is stored (``app.content.store``). A download is a single-use
link valid for ``[files] download_url_ttl_seconds`` (60): its token is random, only the
token's SHA-256 is stored (``downloads``), and redeeming it checks the user, the
expiry and that it was not used, then reads our stored copy. RAGFlow is never asked
for a file. Links are capped per user per UTC day (``downloads_per_user_per_day``).

Everything here runs in the caller's tenant-scoped transaction.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import Source
from app.content.store import STORABLE_TYPES
from app.files.models import Download
from app.tenancy.workspaces import Workspace

PAGE_TYPES = ("html", "markdown")
UTC_MIDNIGHT = text("date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'")


class FileRefused(Exception):
    """The file cannot be listed or downloaded. ``code`` is safe to log and to return."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SiteRollup:
    site: str
    publisher: str
    page_count: int
    last_ingested_on: date


@dataclass(frozen=True)
class IssuedLink:
    download_id: uuid.UUID
    token: str
    expires_at: datetime


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_downloadable(source: Source) -> bool:
    """The licence gate is open and our own copy exists."""
    return bool(source.downloadable and source.stored_path and source.type in STORABLE_TYPES)


async def _workspace_tags(session: AsyncSession, workspace_id: uuid.UUID) -> list[str]:
    tags = await session.scalar(select(Workspace.tag_ids).where(Workspace.id == workspace_id))
    if tags is None:
        raise FileRefused("not_found")  # another tenant's, or no such workspace
    return list(tags)


def _in_workspace(tags: list[str]) -> Any:
    return Source.tags.overlap(tags) & (Source.status == "ingested")


async def workspace_files(
    session: AsyncSession, workspace_id: uuid.UUID
) -> tuple[list[Source], list[SiteRollup]]:
    """The workspace's files, and its crawled sites rolled up (one entry per site)."""
    tags = await _workspace_tags(session, workspace_id)
    if not tags:
        return [], []
    rows = (
        await session.scalars(
            select(Source)
            .where(_in_workspace(tags), Source.type.in_((*STORABLE_TYPES, *PAGE_TYPES)))
            .order_by(Source.publisher, Source.title, Source.id)
        )
    ).all()
    files = [s for s in rows if s.type in STORABLE_TYPES]
    pages: dict[str, list[Source]] = defaultdict(list)
    for source in rows:
        if source.type in PAGE_TYPES:
            host = urlsplit(source.canonical_url or "").hostname
            pages[host or source.publisher].append(source)
    sites = [
        SiteRollup(
            site=site,
            publisher=members[0].publisher,
            page_count=len(members),
            last_ingested_on=max(m.created_at for m in members).date(),
        )
        for site, members in sorted(pages.items())
    ]
    return files, sites


async def _file_in_workspace(
    session: AsyncSession, workspace_id: uuid.UUID, source_id: uuid.UUID
) -> Source:
    tags = await _workspace_tags(session, workspace_id)
    source = await session.scalar(
        select(Source).where(
            Source.id == source_id, _in_workspace(tags), Source.type.in_(STORABLE_TYPES)
        )
    )
    if source is None:
        raise FileRefused("not_found")
    return source


async def downloads_today(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Links issued to the user since midnight UTC."""
    count = await session.scalar(
        select(func.count())
        .select_from(Download)
        .where(
            Download.user_id == user_id,
            Download.created_at >= UTC_MIDNIGHT,
        )
    )
    return int(count or 0)


async def issue_link(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    ttl_seconds: int,
    daily_cap: int,
) -> IssuedLink:
    """A single-use download link for a downloadable file of the workspace.

    Refuses ``not_found`` (not a file of this workspace), ``not_downloadable`` (licence
    gate closed or no stored copy) and ``download_cap_reached``.
    """
    source = await _file_in_workspace(session, workspace_id, source_id)
    if not is_downloadable(source):
        raise FileRefused("not_downloadable")
    # One user's concurrent requests queue here, so the cap holds under concurrency.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"downloads:{user_id}"},
    )
    if await downloads_today(session, user_id) >= daily_cap:
        raise FileRefused("download_cap_reached")
    token = secrets.token_urlsafe(32)
    download = Download(
        tenant_id=tenant_id,
        user_id=user_id,
        workspace_id=workspace_id,
        source_id=source.id,
        token_sha256=token_digest(token),
        expires_at=func.now() + timedelta(seconds=ttl_seconds),
    )
    session.add(download)
    await session.flush()
    await session.refresh(download)
    return IssuedLink(download_id=download.id, token=token, expires_at=download.expires_at)


async def redeem(session: AsyncSession, *, user_id: uuid.UUID, token: str) -> Source:
    """The source behind an unexpired, unused link of this user; marks the link used.

    Re-checks that the file is still in the workspace and still downloadable, since the
    operator or the package may have changed since the link was issued.
    """
    download = await session.scalar(
        select(Download)
        .where(
            Download.token_sha256 == token_digest(token),
            Download.user_id == user_id,
            Download.served_at.is_(None),
            Download.expires_at > func.now(),
        )
        .with_for_update()
    )
    if download is None:
        raise FileRefused("not_found")
    source = await _file_in_workspace(session, download.workspace_id, download.source_id)
    if not is_downloadable(source):
        raise FileRefused("not_found")
    await session.execute(
        update(Download).where(Download.id == download.id).values(served_at=func.now())
    )
    return source
