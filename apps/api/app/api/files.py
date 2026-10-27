"""/api/v1 workspace file list and downloads (P1a-14). See ``app.files.service``.

``GET /workspaces/{id}/files`` lists the workspace's files and sites for any signed-in
user of the tenant. ``POST /workspaces/{id}/files/{source_id}/download`` issues a
single-use link valid for 60 seconds, audited as ``download`` with the source ID and
capped per user per day; ``GET /files/{token}`` serves our own stored copy of the file.
Nothing is fetched from RAGFlow, and no RAGFlow dataset or document ID is returned.
Logs carry source IDs only, never titles or file names.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_tenant_id, current_user_id, db_session
from app.api.schemas import (
    DownloadLinkOut,
    WorkspaceFileOut,
    WorkspaceFilesOut,
    WorkspaceSiteOut,
    WorkspaceSummaryOut,
)
from app.audit.writer import record
from app.consent.gate import require_consent
from app.content import store
from app.content.ingest import MEDIA_TYPE_BY_TYPE, SUFFIX_BY_TYPE
from app.core import cache
from app.core.db import tenant_session
from app.core.logging import log
from app.files.service import (
    SUMMARY_KEY,
    SUMMARY_TTL_SECONDS,
    FileRefused,
    is_downloadable,
    issue_link,
    redeem,
    require_workspace,
    workspace_files,
    workspace_summary,
)

# P1b-10: file lists and downloads need the active notice accepted.
router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_consent)])

FILES_PATH = "/api/v1/files/"
MEDIA_TYPES = MEDIA_TYPE_BY_TYPE
_REFUSALS = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "not_downloadable": status.HTTP_403_FORBIDDEN,
    "download_cap_reached": status.HTTP_429_TOO_MANY_REQUESTS,
}
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def _refused(exc: FileRefused) -> HTTPException:
    # P2A-02: a paused file is answered exactly as one outside the workspace.
    detail = "not_found" if exc.code == "paused" else exc.code
    return HTTPException(_REFUSALS.get(exc.code, status.HTTP_404_NOT_FOUND), detail=detail)


@router.get("/workspaces/{workspace_id}/files", response_model=WorkspaceFilesOut)
async def list_workspace_files(
    workspace_id: UUID, session: AsyncSession = Depends(db_session)
) -> WorkspaceFilesOut:
    """The workspace's PDF, DOCX and PPTX files and its crawled sites. No search or
    filters (Phase 1a)."""
    try:
        files, sites = await workspace_files(session, workspace_id)
    except FileRefused as exc:
        raise _refused(exc) from None
    return WorkspaceFilesOut(
        files=[
            WorkspaceFileOut(
                id=f.id,
                type=f.type,
                title=f.title,
                publisher=f.publisher,
                published_on=f.published_on,
                canonical_url=f.canonical_url,
                ingested_on=f.created_at.date(),
                downloadable=is_downloadable(f),
            )
            for f in files
        ],
        sites=[
            WorkspaceSiteOut(
                site=s.site,
                publisher=s.publisher,
                page_count=s.page_count,
                last_ingested_on=s.last_ingested_on,
            )
            for s in sites
        ],
    )


@router.get("/workspaces/{workspace_id}/summary", response_model=WorkspaceSummaryOut)
async def get_workspace_summary(
    workspace_id: UUID, request: Request, session: AsyncSession = Depends(db_session)
) -> WorkspaceSummaryOut:
    """P2B-05: document count, publishers, years and last update of the workspace, for the
    home page. Cached per workspace under a tenant-prefixed key; any change to the tenant's
    library clears it (``app.core.library_events``). The cache is an aid: if it cannot be
    reached the summary is computed."""
    tenant_id = current_tenant_id(request)
    key = f"{SUMMARY_KEY}{workspace_id}"
    try:
        await require_workspace(session, workspace_id)  # 404 for another tenant's
    except FileRefused as exc:
        raise _refused(exc) from None
    try:
        cached = await cache.get(tenant_id, key)
        if cached is not None:
            return WorkspaceSummaryOut.model_validate_json(cached)
    except Exception as exc:  # a cache fault or a stale shape: compute instead
        log("workspace_summary.cache_read_failed", "warning", error_code=type(exc).__name__)
    summary = await workspace_summary(session, workspace_id)
    out = WorkspaceSummaryOut(**asdict(summary))
    try:
        await cache.set(tenant_id, key, out.model_dump_json(), SUMMARY_TTL_SECONDS)
    except Exception as exc:
        log("workspace_summary.cache_write_failed", "warning", error_code=type(exc).__name__)
    return out


@router.post(
    "/workspaces/{workspace_id}/files/{source_id}/download",
    status_code=status.HTTP_201_CREATED,
    response_model=DownloadLinkOut,
    responses={
        403: {"description": "The file is listed but not downloadable"},
        404: {"description": "Not a file of this workspace"},
        429: {"description": "The daily download cap is reached"},
    },
)
async def request_download(
    workspace_id: UUID,
    source_id: UUID,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> DownloadLinkOut:
    tenant_id, user_id = current_tenant_id(request), current_user_id(request)
    files = request.app.state.settings.models.files
    try:
        link = await issue_link(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            workspace_id=workspace_id,
            source_id=source_id,
            ttl_seconds=files.download_url_ttl_seconds,
            daily_cap=files.downloads_per_user_per_day,
        )
    except FileRefused as exc:
        if exc.code in ("download_cap_reached", "paused"):
            # Refusals at the cap are audited too (bulk-extraction control, CC6.6), and a
            # paused file's (P2A-02).
            await session.rollback()
            await _audit_refusal(request, tenant_id, user_id, workspace_id, source_id, exc.code)
        log("files.download_refused", tenant_id=str(tenant_id), error_code=exc.code)
        raise _refused(exc) from None
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=user_id,
        event="download",
        metadata={"source_id": str(source_id), "workspace_id": str(workspace_id)},
    )
    log(
        "files.download_issued",
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        source_id=str(source_id),
    )
    out = DownloadLinkOut(url=f"{FILES_PATH}{link.token}", expires_at=link.expires_at)
    await session.commit()
    return out


async def _audit_refusal(
    request: Request,
    tenant_id: UUID,
    user_id: UUID,
    workspace_id: UUID,
    source_id: UUID,
    code: str,
) -> None:
    async with tenant_session(request.app.state.db_factory, tenant_id) as audit:
        await record(
            audit,
            tenant_id=tenant_id,
            actor_user_id=user_id,
            event="download.refused",
            metadata={
                "source_id": str(source_id),
                "workspace_id": str(workspace_id),
                "error_code": code,
            },
        )


@router.get(
    "/files/{token}",
    response_class=Response,
    responses={
        200: {"description": "The file", "content": {m: {} for m in MEDIA_TYPES.values()}},
        404: {"description": "Unknown, expired or already used link"},
    },
)
async def download_file(
    token: str, request: Request, session: AsyncSession = Depends(db_session)
) -> Response:
    """Serve our stored copy of the file behind a single-use link of this user."""
    tenant_id, user_id = current_tenant_id(request), current_user_id(request)
    if not _TOKEN.fullmatch(token):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        source = await redeem(session, user_id=user_id, token=token)
    except FileRefused as exc:
        if exc.paused is not None:  # a link issued before the source was paused (P2A-02)
            workspace_id, source_id = exc.paused
            await session.rollback()
            await _audit_refusal(request, tenant_id, user_id, workspace_id, source_id, exc.code)
            log("files.download_refused", tenant_id=str(tenant_id), error_code=exc.code)
        raise _refused(exc) from None
    if source.stored_path is None or source.file_sha256 is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        content = store.read(
            request.app.state.settings.models.files.content_root,
            source.stored_path,
            source.file_sha256,
        )
    except store.StoredFileError as exc:
        log(
            "files.stored_copy_unusable",
            level="error",
            source_id=str(source.id),
            error_code=exc.code,
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="file_unavailable") from None
    await session.commit()  # the link is used only once the bytes are in hand
    log("files.download_served", tenant_id=str(tenant_id), source_id=str(source.id))
    return Response(
        content=content,
        media_type=MEDIA_TYPES[source.type],
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(source.title, source.type)}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _filename(title: str, source_type: str) -> str:
    """An ASCII file name from the title, never the original upload's name."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:80] or "document"
    return slug + SUFFIX_BY_TYPE[source_type]
