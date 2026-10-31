"""P2SR01: the uploaded-crawl routes of the content console over HTTP in OIDC mode,
against PostgreSQL, a fake RAGFlow and the synthetic ZIPs of
``packages/eval/fixtures/uploads/``. Who may upload, what is staged and refused, and
that no member name, URL or title is logged or audited."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.tenancy.models import INTERNAL_TENANT_ID
from tests.fakes import FakeRedis
from tests.test_auth import Auth, auth
from tests.test_content_console import API, Console
from tests.test_crawler import resolver
from tests.test_ingest import Env, Ingest, env
from tests.test_tenancy import Tenant

__all__ = ["auth", "env"]  # the fixtures, imported for their use here

UPLOADS = Path(__file__).resolve().parents[3] / "packages" / "eval" / "fixtures" / "uploads"
START = "https://www.example.org/"
PUBLIC = {"site.example": ["93.184.216.34"], "www.example.org": ["93.184.215.14"]}
SITE_FIELDS = {
    "start_url": START,
    "name": "Synthetic Pantry",
    "publisher": "Synthetic Pantry Co",
    "licence_basis": "publisher-terms",
    "tags": "sample-web",
}
# What a member name, URL or title of the fixtures looks like; never in a log or audit row.
NAMES = ("Gravies", "Broth", "Soup", "Synthetic Pantry -", "/Products", "site/")


class Uploads(Console):
    def __init__(self, auth: Auth, e: Env) -> None:
        super().__init__(auth, e)
        auth.app.state.content_resolve = resolver(PUBLIC)

    async def upload(
        self,
        client: httpx.AsyncClient,
        name: str = "markdown-new.zip",
        *,
        site_id: UUID | str | None = None,
        content: bytes | None = None,
        **fields: Any,
    ) -> httpx.Response:
        data: dict[str, Any] = {
            "crawled_on": "2026-10-30",
            "mode": "partial",
            "declared_robots_honoured": "true",
        }
        if site_id is None:
            data |= SITE_FIELDS
        data |= fields
        payload = content if content is not None else (UPLOADS / name).read_bytes()
        files = {"file": ("crawl.zip", payload, "application/zip")}
        path = f"{API}/sites/uploads" if site_id is None else f"{API}/sites/{site_id}/uploads"
        return await client.post(path, data=data, files=files)

    async def audit_rows(self) -> list[str]:
        rows = await self.auth.admin.fetch(
            "SELECT event, metadata::text AS m FROM audit_events WHERE tenant_id = $1",
            INTERNAL_TENANT_ID,
        )
        return [f"{r['event']} {r['m']}" for r in rows]

    async def upload_row(self, upload_id: str) -> Any:
        return await self.auth.admin.fetchrow(
            "SELECT * FROM site_uploads WHERE id = $1", UUID(upload_id)
        )


@pytest.fixture
async def uploads(auth: Auth, env: tuple[Env, Ingest], redis: FakeRedis) -> AsyncIterator[Uploads]:
    e, _ = env
    yield Uploads(auth, e)
    await auth.admin.execute("DELETE FROM conversations")


def no_names(text: str) -> None:
    for name in NAMES:
        assert name not in text, name


# --- P2SR01-02 who may upload, and what is staged ----------------------------------------


async def test_an_editor_stages_a_new_upload_site_and_sees_the_report_once(
    uploads: Uploads, capsys: pytest.CaptureFixture[str]
) -> None:
    await uploads.roles("content_editor")
    response = await uploads.upload(uploads.editor())
    assert response.status_code == 201, response.text
    report = response.json()
    assert (report["status"], report["mode"], report["crawled_on"]) == (
        "staged",
        "partial",
        "2026-10-30",
    )
    assert (report["accepted"], report["refused"], report["skipped"]) == (3, 0, 5)
    assert report["would_withdraw"] is None
    accepted = [m for m in report["members"] if m["outcome"] == "accepted"]
    assert [(m["name"], m["url"]) for m in accepted] == [
        ("site/Products/Gravies.md", "https://www.example.org/Products/Gravies"),
        ("site/Products/Broth.md", "https://www.example.org/Products/Broth"),
        ("site/Recipes/Soup.markdown", "https://www.example.org/Recipes/Soup"),
    ]
    site = await uploads.auth.admin.fetchrow(
        "SELECT * FROM sites WHERE id = $1", UUID(report["site_id"])
    )
    assert (site["origin"], site["status"], site["schedule"], site["next_crawl_at"]) == (
        "upload",
        "proposed",
        "none",
        None,
    )
    row = await uploads.upload_row(report["upload_id"])
    assert (row["status"], row["mode"], row["declared_robots_honoured"]) == (
        "staged",
        "partial",
        True,
    )
    assert (row["member_count"], row["accepted_count"], row["skipped_count"]) == (8, 3, 5)
    # Staged by hash under content_root; the row holds counts and codes, never a name.
    staged = uploads.e.content_root / row["staged_path"]
    assert row["staged_path"] == f"uploads/{row['zip_sha256']}.zip"
    assert staged.read_bytes() == (UPLOADS / "markdown-new.zip").read_bytes()
    no_names(json.dumps({k: str(v) for k, v in dict(row).items()}))
    # Nothing reached RAGFlow, no register row, no job.
    assert uploads.e.fake.uploads == []
    assert await uploads.auth.admin.fetchval("SELECT count(*) FROM sources") == 0
    assert await uploads.auth.admin.fetchval("SELECT count(*) FROM jobs") == 0
    [event] = await uploads.events("site.upload_staged", "upload_id", report["upload_id"])
    assert {k: event[k] for k in ("site_id", "mode", "members", "accepted", "skipped")} == {
        "site_id": report["site_id"],
        "mode": "partial",
        "members": 8,
        "accepted": 3,
        "skipped": 5,
    }
    no_names("\n".join(await uploads.audit_rows()))
    no_names(capsys.readouterr().out)
    # The site detail lists the upload with counts only.
    detail = (await uploads.editor().get(f"{API}/sites/{report['site_id']}")).json()
    assert detail["origin"] == "upload"
    [listed] = detail["uploads"]
    assert (listed["status"], listed["accepted_count"], listed["uploaded_by"]) == (
        "staged",
        3,
        "editor@example.org",
    )
    no_names(json.dumps(detail["uploads"]))


async def test_a_whole_upload_refusal_gives_the_code_and_index_and_stages_nothing(
    uploads: Uploads, capsys: pytest.CaptureFixture[str]
) -> None:
    await uploads.roles("content_editor")
    for name, code, member in (
        ("dotdot-name.zip", "unsafe_member", 1),
        ("nested-zip.zip", "unsafe_member", 1),
        ("duplicate-url.zip", "duplicate_url", 1),
        ("no-pages.zip", "no_pages", None),
        ("not-a-zip.zip", "not_a_zip", None),
    ):
        response = await uploads.upload(uploads.editor(), name)
        assert response.status_code == 422, name
        assert response.json() == {"detail": {"code": code, "member": member}}
    assert await uploads.auth.admin.fetchval("SELECT count(*) FROM sites") == 0
    assert await uploads.auth.admin.fetchval("SELECT count(*) FROM site_uploads") == 0
    assert not (uploads.e.content_root / "uploads").exists()
    no_names(capsys.readouterr().out)


async def test_member_refusals_are_listed_and_the_rest_is_staged(uploads: Uploads) -> None:
    await uploads.roles("content_editor")
    response = await uploads.upload(uploads.editor(), "off-site.zip")
    assert response.status_code == 201, response.text
    body = response.json()
    assert [m["outcome"] for m in body["members"]] == ["accepted", "off_site"]
    assert (body["accepted"], body["refused"]) == (1, 1)
    row = await uploads.upload_row(body["upload_id"])
    assert (row["accepted_count"], row["refused_count"]) == (1, 1)


async def test_upload_refusals_before_and_after_the_body(uploads: Uploads) -> None:
    await uploads.roles("content_editor")
    editor = uploads.editor()
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    for fields, code in (
        ({"declared_robots_honoured": "false"}, "declaration_required"),
        ({"crawled_on": tomorrow}, "crawled_in_future"),
    ):
        response = await uploads.upload(editor, **fields)
        assert (response.status_code, response.json()["detail"]) == (422, code)
    assert (await uploads.upload(editor, mode="sometimes")).status_code == 422
    assert (await uploads.upload(editor, content=b"")).status_code == 422
    assert await uploads.auth.admin.fetchval("SELECT count(*) FROM sites") == 0

    first = (await uploads.upload(editor)).json()
    site_id = first["site_id"]
    # D10: one pending upload per site.
    response = await uploads.upload(editor, site_id=site_id)
    assert (response.status_code, response.json()["detail"]) == (409, "upload_pending")
    # A new upload site at a registered start URL is refused, not merged.
    response = await uploads.upload(editor)
    assert (response.status_code, response.json()["detail"]) == (409, "site_exists")
    # A live-crawl site never takes an upload.
    crawled = await editor.post(
        f"{API}/sites",
        json={
            "start_url": "https://site.example/",
            "name": "n",
            "publisher": "p",
            "licence_basis": "l",
            "tags": ["sample-web"],
        },
    )
    assert crawled.status_code == 201, crawled.text
    response = await uploads.upload(editor, site_id=crawled.json()["id"])
    assert (response.status_code, response.json()["detail"]) == (409, "origin_crawl")
    # A withdrawn or rejected upload site takes none either.
    await uploads.auth.admin.execute(
        "UPDATE site_uploads SET status = 'rejected', review_note = 'n'"
    )
    for status, extra in (
        ("rejected", ""),
        ("withdrawn", ", withdrawn_at = now(), withdrawal_reason = 'r', approved_at = now()"),
    ):
        await uploads.auth.admin.execute(
            f"UPDATE sites SET status = '{status}'{extra} WHERE id = $1", UUID(site_id)
        )
        response = await uploads.upload(editor, site_id=site_id)
        assert (response.status_code, response.json()["detail"]) == (409, f"site_{status}")
    unknown = "00000000-0000-4000-8000-0000000000aa"
    assert (await uploads.upload(editor, site_id=unknown)).status_code == 404
    # A start URL that does not resolve to a public address is refused (P1b-18).
    response = await uploads.upload(editor, start_url="https://unknown.example/")
    assert response.status_code == 422


async def test_only_an_editor_may_upload(uploads: Uploads) -> None:
    await uploads.roles("content_reviewer")
    response = await uploads.upload(uploads.editor())
    assert response.status_code == 403
    response = await uploads.upload(uploads.as_user("analyst@example.org"))
    assert response.status_code == 403
    for role in ("tenant_admin", "user"):
        tenant: Tenant = await uploads.auth.tenant(role=role)
        response = await uploads.upload(uploads.as_user(tenant.email, tenant.id))
        assert response.status_code == 403
    assert await uploads.auth.admin.fetchval("SELECT count(*) FROM sites") == 0
    assert not uploads.e.content_root.exists()


async def test_an_upload_cannot_name_datasets_or_documents(uploads: Uploads) -> None:
    """Extra form fields are ignored, never read: the datasets come from the site's tags."""
    await uploads.roles("content_editor")
    response = await uploads.upload(
        uploads.editor(), dataset_ids="ds-1", document_ids="doc-1", tags="sample-web"
    )
    assert response.status_code == 201
    assert "ds-1" not in json.dumps(await uploads.audit_rows())
