"""P1a-14: workspace file list and downloads, over HTTP against PostgreSQL as the
application role. Files are synthetic bytes stored under a temporary content root."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from app.content import store
from app.core.config import FilesConfig
from app.core.db import tenant_session
from app.files.service import workspace_files
from tests.test_api import EDITOR, Harness, api  # noqa: F401 - fixture
from tests.test_tenancy import make_tenant

pytestmark = pytest.mark.usefixtures("database")

CAP = 3


@dataclass
class Files:
    api: Harness
    admin: asyncpg.Connection
    root: Path
    workspace: uuid.UUID  # internal tenant, tag sample-reports only
    created: list[uuid.UUID] = field(default_factory=list)

    async def source(
        self,
        *,
        kind: str = "pdf",
        tag: str = "sample-reports",
        downloadable: bool = True,
        stored: bool = True,
        title: str | None = None,
        url: str = "https://example.org/synthetic",
    ) -> uuid.UUID:
        content = f"synthetic {kind} {uuid.uuid4()}".encode()
        sha = hashlib.sha256(content).hexdigest()
        path = store.store(self.root, sha, kind, content) if stored else None
        source_id: uuid.UUID = await self.admin.fetchval(
            "INSERT INTO sources (type, title, publisher, published_on, canonical_url, "
            "licence_basis, tags, status, file_sha256, ragflow_document_ids, downloadable, "
            "stored_path, approved_at) VALUES ($1, $2, 'Synthetic Publisher', '2026-03-01', $3, "
            "'public', ARRAY[$4], 'ingested', $5, $6::jsonb, $7, $8, now()) RETURNING id",
            kind,
            title or f"Synthetic {kind} {uuid.uuid4().hex[:6]}",
            url,
            tag,
            sha,
            json.dumps({"ds-reports-0001": f"doc-{uuid.uuid4().hex[:12]}"}),
            downloadable,
            path,
        )
        self.created.append(source_id)
        return source_id

    async def link(self, source_id: uuid.UUID, *, workspace: uuid.UUID | None = None, **kw: Any):
        wid = workspace or self.workspace
        return await self.api.request("POST", f"/workspaces/{wid}/files/{source_id}/download", **kw)

    async def fetch(self, url: str, **kw: Any):
        assert url.startswith("/api/v1/")
        return await self.api.request("GET", url.removeprefix("/api/v1"), **kw)

    async def audit(self, event: str) -> list[dict[str, Any]]:
        rows = await self.admin.fetch(
            "SELECT actor_user_id, metadata FROM audit_events WHERE event = $1 "
            "AND metadata->>'workspace_id' = $2 ORDER BY created_at",
            event,
            str(self.workspace),
        )
        return [{"actor": r["actor_user_id"], **json.loads(r["metadata"])} for r in rows]


@pytest.fixture
async def files(
    api: Harness,  # noqa: F811
    admin_conn: asyncpg.Connection,
    tmp_path: Path,
) -> AsyncIterator[Files]:
    api.app.state.settings.models = api.app.state.settings.models.model_copy(
        update={"files": FilesConfig(content_root=tmp_path, downloads_per_user_per_day=CAP)}
    )
    workspace = await api.world.new_workspace(["sample-reports"])
    harness = Files(api, admin_conn, tmp_path, workspace)
    yield harness
    for source_id in harness.created:
        await admin_conn.execute("DELETE FROM sources WHERE id = $1", source_id)


# --- the list ---------------------------------------------------------------------------


async def test_lists_files_in_the_workspace_tags_with_register_fields(files: Files) -> None:
    pdf = await files.source(title="Synthetic Outlook")
    docx = await files.source(kind="docx", downloadable=False)
    outside = await files.source(kind="pptx", tag="sample-analysis")
    response = await files.api.request("GET", f"/workspaces/{files.workspace}/files")
    assert response.status_code == 200
    listed = {f["id"]: f for f in response.json()["files"]}
    assert str(outside) not in listed  # a tag outside the workspace
    assert listed[str(pdf)] == {
        "id": str(pdf),
        "type": "pdf",
        "title": "Synthetic Outlook",
        "publisher": "Synthetic Publisher",
        "published_on": "2026-03-01",
        "canonical_url": "https://example.org/synthetic",
        "ingested_on": datetime.now().date().isoformat(),
        "downloadable": True,
    }
    assert listed[str(docx)]["downloadable"] is False


async def test_crawled_sites_appear_once_with_a_page_count(files: Files) -> None:
    for n in range(3):
        await files.source(kind="markdown", stored=False, downloadable=False,
                           url=f"https://site-a.example/page-{n}")  # fmt: skip
    await files.source(kind="html", stored=False, downloadable=False,
                       url="https://site-b.example/")  # fmt: skip
    body = (await files.api.request("GET", f"/workspaces/{files.workspace}/files")).json()
    sites = {s["site"]: s for s in body["sites"]}
    assert sites["site-a.example"]["page_count"] == 3
    assert sites["site-b.example"]["page_count"] == 1
    assert all(f["type"] in ("pdf", "docx", "pptx") for f in body["files"])


async def test_response_carries_no_dataset_or_document_ids(files: Files) -> None:
    mine = await files.source()
    rows = await files.admin.fetch("SELECT ragflow_document_ids FROM sources")
    ragflow_ids = {"ds-reports-0001", "ds-analysis-0001"}
    for row in rows:
        mapping = json.loads(row["ragflow_document_ids"])
        values = mapping.values() if isinstance(mapping, dict) else mapping
        ragflow_ids |= {str(v) for v in values} | set(mapping if isinstance(mapping, dict) else ())
    body = (await files.api.request("GET", f"/workspaces/{files.workspace}/files")).json()
    link = (await files.link(mine)).json()
    for payload in (body, link):
        text = json.dumps(payload)
        assert not [i for i in ragflow_ids if i in text]
    assert set(body) == {"files", "sites"}
    for item in body["files"]:
        uuid.UUID(item["id"])  # our register's UUID
        assert set(item) == {
            "id", "type", "title", "publisher", "published_on", "canonical_url",
            "ingested_on", "downloadable",
        }  # fmt: skip
    assert set(link) == {"url", "expires_at"}


async def test_another_tenants_workspace_is_not_found(
    files: Files, admin_conn: asyncpg.Connection
) -> None:
    source = await files.source()
    other = await make_tenant(admin_conn)
    await admin_conn.execute(
        "UPDATE workspaces SET tag_ids = ARRAY['sample-reports'] WHERE tenant_id = $1", other.id
    )
    foreign = await admin_conn.fetchval("SELECT id FROM workspaces WHERE tenant_id = $1", other.id)
    assert (await files.api.request("GET", f"/workspaces/{foreign}/files")).status_code == 404
    assert (await files.link(source, workspace=foreign)).status_code == 404


# --- downloads --------------------------------------------------------------------------


async def test_a_file_outside_the_workspace_is_not_downloadable_by_direct_url(
    files: Files,
) -> None:
    outside = await files.source(kind="pptx", tag="sample-analysis")
    response = await files.link(outside)
    assert (response.status_code, response.json()["detail"]) == (404, "not_found")
    # Neither is any guess at the file route itself.
    for guess in (str(outside), "x" * 43, f"{outside}{outside}".replace("-", "")):
        assert (await files.fetch(f"/api/v1/files/{guess}")).status_code == 404
    assert await files.audit("download") == []


async def test_listed_file_that_is_not_downloadable_is_refused(files: Files) -> None:
    gated = await files.source(downloadable=False)
    unstored = await files.source(stored=False)  # flag set, but no copy of ours
    for source in (gated, unstored):
        response = await files.link(source)
        assert (response.status_code, response.json()["detail"]) == (403, "not_downloadable")
    assert await files.audit("download") == []


async def test_download_serves_our_stored_copy_once_and_is_audited(
    files: Files, capsys: pytest.CaptureFixture[str]
) -> None:
    source = await files.source(title="Synthetic Outlook: 2026 edition")
    response = await files.link(source)
    assert response.status_code == 201
    link = response.json()
    issued = datetime.fromisoformat(link["expires_at"]) - datetime.now().astimezone()
    assert timedelta(seconds=50) < issued <= timedelta(seconds=60)

    served = await files.fetch(link["url"])
    assert served.status_code == 200
    row = await files.admin.fetchrow(
        "SELECT file_sha256, stored_path FROM sources WHERE id = $1", source
    )
    assert served.content == (files.root / row["stored_path"]).read_bytes()
    assert hashlib.sha256(served.content).hexdigest() == row["file_sha256"]
    assert served.headers["content-type"] == "application/pdf"
    assert served.headers["content-disposition"] == (
        'attachment; filename="Synthetic-Outlook-2026-edition.pdf"'
    )
    assert served.headers["cache-control"] == "no-store"
    # Single use.
    assert (await files.fetch(link["url"])).status_code == 404
    # Nothing came from RAGFlow.
    assert files.api.retriever.calls == []

    (event,) = await files.audit("download")
    assert event == {
        "actor": files.api.world.user_id,
        "source_id": str(source),
        "workspace_id": str(files.workspace),
    }
    # Logs carry the source ID, never the title or the token.
    out = capsys.readouterr().out
    assert str(source) in out
    assert "Synthetic Outlook" not in out
    assert link["url"].rsplit("/", 1)[1] not in out


async def test_the_link_expires(files: Files) -> None:
    source = await files.source()
    link = (await files.link(source)).json()
    await files.admin.execute(
        "UPDATE downloads SET expires_at = now() - interval '1 second' WHERE source_id = $1",
        source,
    )
    assert (await files.fetch(link["url"])).status_code == 404
    stored = await files.admin.fetchval(
        "SELECT token_sha256 FROM downloads WHERE source_id = $1", source
    )
    token = link["url"].rsplit("/", 1)[1]
    assert stored == hashlib.sha256(token.encode()).hexdigest()  # only the hash is kept


async def test_a_link_works_only_for_the_user_it_was_issued_to(files: Files) -> None:
    source = await files.source()
    link = (await files.link(source)).json()
    assert (await files.fetch(link["url"], email=EDITOR)).status_code == 404
    assert (await files.fetch(link["url"])).status_code == 200


async def test_closing_the_gate_after_issue_refuses_the_link(files: Files) -> None:
    source = await files.source()
    link = (await files.link(source)).json()
    await files.admin.execute("UPDATE sources SET downloadable = false WHERE id = $1", source)
    assert (await files.fetch(link["url"])).status_code == 404


async def test_a_tampered_copy_is_not_served(files: Files) -> None:
    source = await files.source()
    path = await files.admin.fetchval("SELECT stored_path FROM sources WHERE id = $1", source)
    (files.root / path).write_bytes(b"something else")
    link = (await files.link(source)).json()
    response = await files.fetch(link["url"])
    assert (response.status_code, response.json()["detail"]) == (404, "file_unavailable")


async def test_daily_cap_is_enforced_per_user_and_audited(files: Files) -> None:
    source = await files.source()
    for _ in range(CAP):
        assert (await files.link(source)).status_code == 201
    refused = await files.link(source)
    assert (refused.status_code, refused.json()["detail"]) == (429, "download_cap_reached")
    assert len(await files.audit("download")) == CAP
    (event,) = await files.audit("download.refused")
    assert event["error_code"] == "download_cap_reached"
    assert event["source_id"] == str(source)
    # Another user's allowance is their own; yesterday's links do not count.
    assert (await files.link(source, email=EDITOR)).status_code == 201
    await files.admin.execute(
        "UPDATE downloads SET created_at = created_at - interval '1 day', "
        "expires_at = expires_at - interval '1 day' WHERE user_id = $1",
        files.api.world.user_id,
    )
    assert (await files.link(source)).status_code == 201


def test_store_refuses_paths_outside_the_root(tmp_path: Path) -> None:
    sha = "0" * 64
    with pytest.raises(store.StoredFileError):
        store.read(tmp_path, "../../etc/passwd", sha)
    with pytest.raises(store.StoredFileError) as missing:
        store.read(tmp_path, f"00/{sha}.pdf", sha)
    assert missing.value.code == "file_missing"


# --- P2A-02: a paused source ------------------------------------------------------------


async def set_paused(admin: asyncpg.Connection, source_id: uuid.UUID, paused: bool) -> None:
    """The register row as ``register.pause`` / ``resume`` leave it (tested in test_pause)."""
    if paused:
        await admin.execute(
            "UPDATE sources SET status = 'paused', paused_at = now(), "
            "paused_by = gen_random_uuid(), pause_reason = 'synthetic' WHERE id = $1",
            source_id,
        )
    else:
        await admin.execute(
            "UPDATE sources SET status = 'ingested', paused_at = NULL, paused_by = NULL, "
            "pause_reason = NULL WHERE id = $1",
            source_id,
        )


async def test_a_paused_file_is_refused_as_not_found_and_audited(files: Files) -> None:
    source = await files.source()
    await set_paused(files.admin, source, True)
    response = await files.link(source)
    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
    assert await files.audit("download") == []
    (event,) = await files.audit("download.refused")
    assert (event["source_id"], event["error_code"]) == (str(source), "paused")
    assert event["actor"] == files.api.world.user_id


async def test_a_link_issued_before_the_pause_is_refused_and_audited(files: Files) -> None:
    source = await files.source()
    link = (await files.link(source)).json()
    await set_paused(files.admin, source, True)
    response = await files.fetch(link["url"])
    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
    (event,) = await files.audit("download.refused")
    assert (event["source_id"], event["error_code"]) == (str(source), "paused")
    served = await files.admin.fetchval(
        "SELECT served_at FROM downloads WHERE source_id = $1", source
    )
    assert served is None


async def test_a_paused_file_leaves_every_tenants_list_and_the_others_stay(
    files: Files, admin_conn: asyncpg.Connection
) -> None:
    paused = await files.source(title="Synthetic paused report")
    kept = await files.source(kind="docx", title="Synthetic kept report")
    pages = [
        await files.source(
            kind="markdown",
            stored=False,
            downloadable=False,
            url=f"https://site-a.example/page-{n}",
        )
        for n in range(3)
    ]
    other = await make_tenant(admin_conn)
    await admin_conn.execute(
        "UPDATE workspaces SET tag_ids = ARRAY['sample-reports'] WHERE tenant_id = $1", other.id
    )
    foreign = await admin_conn.fetchval("SELECT id FROM workspaces WHERE tenant_id = $1", other.id)
    await set_paused(files.admin, paused, True)
    await set_paused(files.admin, pages[0], True)

    body = (await files.api.request("GET", f"/workspaces/{files.workspace}/files")).json()
    listed = {f["id"] for f in body["files"]}
    assert str(paused) not in listed and str(kept) in listed  # the tenant's others stay
    assert {s["site"]: s["page_count"] for s in body["sites"]}["site-a.example"] == 2
    async with tenant_session(files.api.app.state.db_factory, other.id) as session:
        theirs, _ = await workspace_files(session, foreign)
    ids = {s.id for s in theirs}
    assert paused not in ids and kept in ids  # D1: the pause is corpus-wide

    await set_paused(files.admin, paused, False)
    body = (await files.api.request("GET", f"/workspaces/{files.workspace}/files")).json()
    assert {str(paused), str(kept)} <= {f["id"] for f in body["files"]}
    assert (await files.link(paused)).status_code == 201
