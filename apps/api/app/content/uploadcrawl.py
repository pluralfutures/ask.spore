"""Uploaded crawls (P2SR01-03, P2SR01-04): a reviewer's release and the ``import_crawl`` job.

Every upload is released by a content reviewer (D7), also on a site already approved: an
upload's pages are whatever the editor put in the ZIP, so each batch is a reviewed act.

- ``release_upload``: ``staged -> queued``. On a ``proposed`` site the release approves the
  site in the same transaction (``sites.approve_locked``, audited ``site.approved`` as
  today); on an ``approved`` site it releases the upload only; a withdrawn or rejected
  site is refused. The site's allow decision becomes ``declared`` (D3: the uploader's
  declaration, recorded per upload, stands in for the crawler's robots and TDM check).
  Enqueues ``import_crawl`` with ``{"upload_id": ...}`` only. Audited
  ``site.upload_released``.
- ``reject_upload``: ``staged -> rejected`` with the reviewer's note (required); the
  staged ZIP is deleted. Audited ``site.upload_rejected``.
- ``upload_report``: the inspection of a staged upload again, for the reviewer's screen
  (the report with member names is never stored), with the number of live pages a full
  upload would withdraw.
- ``import_crawl`` (the worker): reads the staged ZIP, checks its hash and inspects it
  again, then runs the live crawler's own page logic (``sitecrawl._Crawl``) on each
  accepted member as a page ``Visit``: the scope rules and the special-category check
  with the site's whitelist (blocked), the takedown and duplicate-content checks
  (blocked), unchanged by hash (dates updated), changed (a new approved row that
  supersedes the live one) or new (a new approved row), each in the **releasing
  reviewer's** name with audit ``method = "crawl_upload"``, staged and queued for
  ``ingest_source``. Register rows carry ``fetched_at`` = the crawl date at midnight UTC
  (D9), the front matter's publication date and no snapshot (D8). A paused page's new
  version is ingested paused (P2A-03, keyed on ``supersedes_id``). A ``full`` upload then
  marks every live page absent from the ZIP ``removed`` (``not_in_upload``), and the
  crawler's sweep withdraws what no live page holds any more, holding back what a
  pending supersession still needs, as for a live crawl (P2SR01-04). The site's crawl
  record is finished as for a crawl (``last_crawl_status = 'imported'``, audited
  ``site.crawled``), the upload gets ``imported`` and its counts (audited
  ``site.upload_imported``) and the staged ZIP is deleted. An upload whose ZIP is
  missing, altered or no longer passes inspection fails (``site.upload_failed``, a code)
  before anything on the site changes.

Log lines and audit events carry identifiers, codes and counts only.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Final
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import AuditValue, record
from app.content.crawler import Visit
from app.content.jobs import enqueue
from app.content.models import Site, SiteUpload
from app.content.register import RegisterError
from app.content.roles import REVIEWER, require, roles_of
from app.content.sitecrawl import _Crawl, _finish, _known, _SiteWithdrawn
from app.content.sites import _note, approve_locked
from app.content.store import StoredFileError, remove
from app.content.store import resolve as resolve_path
from app.content.uploads import (
    UploadRefused,
    UploadReport,
    inspect_zip,
    live_urls,
    pages,
    scope_of,
    special_for,
)
from app.core.db import tenant_session
from app.core.logging import log
from app.tenancy.models import INTERNAL_TENANT_ID

METHOD: Final = "crawl_upload"
COUNTED: Final = ("new", "changed", "unchanged", "blocked", "withdrawn")


@dataclass(frozen=True)
class ImportResult:
    upload_id: UUID
    status: str  # imported, failed, refused
    error_code: str | None = None
    site_id: UUID | None = None
    counts: Counter[str] | None = None


async def _audit(
    session: AsyncSession,
    actor: UUID | None,
    event: str,
    upload: SiteUpload,
    **extra: AuditValue,
) -> None:
    await record(
        session,
        tenant_id=INTERNAL_TENANT_ID,
        actor_user_id=actor,
        event=event,
        metadata={
            "upload_id": str(upload.id),
            "site_id": str(upload.site_id),
            "mode": upload.mode,
            **extra,
        },
    )


async def _locked_upload(session: AsyncSession, site_id: UUID, upload_id: UUID) -> SiteUpload:
    upload = await session.scalar(
        select(SiteUpload)
        .where(SiteUpload.id == upload_id, SiteUpload.site_id == site_id)
        .with_for_update()
    )
    if upload is None:
        raise RegisterError("no_upload")
    return upload


async def release_upload(
    factory: async_sessionmaker[AsyncSession],
    site_id: UUID,
    upload_id: UUID,
    reviewer_id: UUID,
    *,
    note: str | None = None,
) -> UUID:
    """A reviewer releases a staged upload (see the module docstring); returns the
    ``import_crawl`` job."""
    checked = _note(note, required=False)
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        site = await session.scalar(select(Site).where(Site.id == site_id).with_for_update())
        if site is None:
            raise RegisterError("no_site")
        upload = await _locked_upload(session, site_id, upload_id)
        if upload.status != "staged":
            raise RegisterError("not_staged")
        if site.origin != "upload":
            raise RegisterError("origin_crawl")
        if site.status in ("withdrawn", "rejected"):
            raise RegisterError("site_" + site.status)
        approves_site = site.status == "proposed"
        if approves_site:
            await approve_locked(session, site, reviewer_id, roles, note=None)
        await session.execute(
            update(Site)
            .where(Site.id == site_id)
            .values(allow_decision="declared", allow_checked_at=func.now(), updated_at=func.now())
        )
        await session.execute(
            update(SiteUpload)
            .where(SiteUpload.id == upload_id)
            .values(
                status="queued",
                released_by=reviewer_id,
                released_at=func.now(),
                review_note=checked,
                updated_at=func.now(),
            )
        )
        job_id = await enqueue(
            session, "import_crawl", {"upload_id": str(upload_id)}, created_by=reviewer_id
        )
        await _audit(
            session,
            reviewer_id,
            "site.upload_released",
            upload,
            before={"status": "staged"},
            after={"status": "queued"},
            roles=sorted(roles),
            self_approval=upload.uploaded_by == reviewer_id,
            status="site_approved" if approves_site else "site_already_approved",
        )
    return job_id


async def reject_upload(
    factory: async_sessionmaker[AsyncSession],
    site_id: UUID,
    upload_id: UUID,
    reviewer_id: UUID,
    *,
    note: str,
    content_root: Path,
) -> None:
    """``staged -> rejected`` with the reviewer's note; the staged ZIP is deleted."""
    checked = _note(note, required=True)
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        upload = await _locked_upload(session, site_id, upload_id)
        if upload.status != "staged":
            raise RegisterError("not_staged")
        staged = _Staged.of(upload)
        await session.execute(
            update(SiteUpload)
            .where(SiteUpload.id == upload_id)
            .values(status="rejected", review_note=checked, staged_path=None, updated_at=func.now())
        )
        await _audit(
            session,
            reviewer_id,
            "site.upload_rejected",
            upload,
            before={"status": "staged"},
            after={"status": "rejected"},
            roles=sorted(roles),
        )
    await _discard(factory, content_root, staged)


@dataclass(frozen=True)
class _Staged:
    upload_id: UUID
    zip_sha256: str
    staged_path: str | None

    @classmethod
    def of(cls, upload: SiteUpload) -> _Staged:
        return cls(upload.id, upload.zip_sha256, upload.staged_path)


async def _discard(
    factory: async_sessionmaker[AsyncSession], content_root: Path, upload: _Staged
) -> None:
    """Delete a finished upload's staged ZIP, unless another pending upload (of another
    site) staged the same bytes: the file is named by its hash."""
    if upload.staged_path is None:
        return
    async with factory() as session:
        shared = await session.scalar(
            select(func.count())
            .select_from(SiteUpload)
            .where(
                SiteUpload.zip_sha256 == upload.zip_sha256,
                SiteUpload.id != upload.upload_id,
                SiteUpload.staged_path.is_not(None),
            )
        )
    if shared:
        return
    try:
        remove(content_root, upload.staged_path)
    except StoredFileError:
        log("content.upload_discard_failed", level="warning", error_code="bad_path")


@dataclass(frozen=True)
class PendingReport:
    upload: SiteUpload
    report: UploadReport
    would_withdraw: int | None


async def upload_report(
    factory: async_sessionmaker[AsyncSession],
    site_id: UUID,
    upload_id: UUID,
    *,
    content_root: Path,
) -> PendingReport:
    """The staged upload's inspection again, for the reviewer (P2SR01-03, D7), and for a
    full upload the number of live pages it would withdraw (P2SR01-04). Raises
    RegisterError (``no_upload``, ``not_staged``, ``upload_missing``) or UploadRefused."""
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        upload = await session.scalar(
            select(SiteUpload).where(SiteUpload.id == upload_id, SiteUpload.site_id == site_id)
        )
        site = await session.get(Site, site_id)
        if upload is None or site is None:
            raise RegisterError("no_upload")
        if upload.status != "staged" or upload.staged_path is None:
            raise RegisterError("not_staged")
        path = _staged_file(content_root, upload)
        report = inspect_zip(path, host=site.host, special=special_for(site), scope=scope_of(site))
        would = None
        if upload.mode == "full":
            would = len(await live_urls(session, site_id) - report.accepted_urls)
    return PendingReport(upload, report, would)


def _staged_file(content_root: Path, upload: SiteUpload) -> Path:
    if upload.staged_path is None:
        raise RegisterError("upload_missing")
    try:
        path = resolve_path(content_root, upload.staged_path)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except (StoredFileError, OSError):
        raise RegisterError("upload_missing") from None
    if digest.hexdigest() != upload.zip_sha256:
        raise RegisterError("upload_altered")
    return path


class _UploadImport(_Crawl):
    method = METHOD


async def _fail(
    factory: async_sessionmaker[AsyncSession], upload: SiteUpload, code: str
) -> ImportResult:
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        await session.execute(
            update(SiteUpload)
            .where(SiteUpload.id == upload.id)
            .values(status="failed", error=code, updated_at=func.now())
        )
        await _audit(
            session,
            None,
            "site.upload_failed",
            upload,
            before={"status": upload.status},
            after={"status": "failed"},
            error_code=code,
            method=METHOD,
        )
    return ImportResult(upload.id, "failed", code, upload.site_id)


async def import_crawl(
    factory: async_sessionmaker[AsyncSession], upload_id: UUID, *, content_root: Path
) -> ImportResult:
    """Run the import of one released upload (see the module docstring)."""
    async with factory() as session:
        upload = await session.get(SiteUpload, upload_id)
        site = await session.get(Site, upload.site_id) if upload is not None else None
    if upload is None or site is None:
        return ImportResult(upload_id, "refused", "no_upload")
    if upload.status != "queued" or upload.released_by is None:
        return ImportResult(upload_id, "refused", "not_queued", site.id)
    if site.origin != "upload":
        return await _fail(factory, upload, "origin_crawl")
    if site.status != "approved":
        return await _fail(factory, upload, "site_not_approved")
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        if REVIEWER not in await roles_of(session, upload.released_by):
            return await _fail(factory, upload, "releaser_lacks_role")
    try:
        path = _staged_file(content_root, upload)
        report = inspect_zip(path, host=site.host)
    except RegisterError as exc:
        return await _fail(factory, upload, exc.code)
    except UploadRefused as exc:
        return await _fail(factory, upload, exc.code)

    staged = _Staged.of(upload)
    importer = _UploadImport(factory, site, await _known(factory, site.id), content_root)
    importer.proposer = upload.uploaded_by
    importer.approver = upload.released_by
    importer.fetched_at = datetime.combine(upload.crawled_on, time(0, 0), tzinfo=UTC)
    scope = scope_of(site)
    special = special_for(site)
    try:
        for page in pages(path, host=site.host):
            if scope is not None and not scope.admits(page.url):
                visit = Visit(page.url, "blocked", "out_of_scope")
            elif category := special(page.url, page.title):
                visit = Visit(page.url, "blocked", "special_category", special_category=category)
            else:
                visit = Visit(
                    page.url,
                    "page",
                    title=page.title,
                    markdown=page.markdown,
                    published_on=page.published_on,
                )
            await importer.apply(visit)
        if upload.mode == "full":
            accepted = report.accepted_urls
            for url, known in importer.known.items():
                if known.state == "live" and url not in accepted:
                    await importer.apply(Visit(url, "missing", "not_in_upload"))
        await importer.sweep()
    except _SiteWithdrawn:
        return await _fail(factory, upload, "site_not_approved")
    await _finish(factory, site, "imported", counts=importer.counts, decision=None)
    counts = importer.counts
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        await session.execute(
            update(SiteUpload)
            .where(SiteUpload.id == upload.id)
            .values(
                status="imported",
                staged_path=None,
                imported_at=func.now(),
                updated_at=func.now(),
                **{f"{k}_count": counts[k] for k in COUNTED},
            )
        )
        await _audit(
            session,
            None,
            "site.upload_imported",
            upload,
            before={"status": "queued"},
            after={"status": "imported"},
            method=METHOD,
            **{k: counts[k] for k in COUNTED},
        )
    await _discard(factory, content_root, staged)
    log(
        "content.upload_imported",
        upload_id=str(upload.id),
        site_id=str(site.id),
        status="imported",
        count=sum(counts[k] for k in ("new", "changed")),
    )
    return ImportResult(upload.id, "imported", None, site.id, counts)
