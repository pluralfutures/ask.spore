"""P1b-05: the content console routes over HTTP in OIDC mode, against PostgreSQL, a fake
RAGFlow and a fake website. Who may reach them, what each role may do, that every action
is audited, and that no document text is shown or logged. Synthetic content only."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.content import worker
from app.content.crawler import HostLimiter
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.fake_idp import sign
from tests.fakes import FakeRedis
from tests.test_auth import Auth, auth
from tests.test_crawler import ROOT, Clock, Site, html, resolver
from tests.test_ingest import PDF, TAGS, Env, Ingest, content_user, env
from tests.test_tenancy import Tenant

__all__ = ["auth", "env"]  # the fixtures, imported for their use here

EDITOR_EMAIL = "editor@example.org"  # seeded internal user (conftest)
PUBLIC = {"site.example": ["93.184.216.34"]}
API = "/api/v1/content"
SOURCE = str(uuid.UUID(int=7))
SITE = str(uuid.UUID(int=8))
# Every content route, with a body that would be valid in shape.
ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", f"{API}/me", None),
    ("GET", f"{API}/sources", None),
    ("GET", f"{API}/sources/{SOURCE}", None),
    ("GET", f"{API}/sources/{SOURCE}/licence", None),
    ("POST", f"{API}/sources/{SOURCE}/approve", {}),
    ("POST", f"{API}/sources/{SOURCE}/reject", {"note": "no"}),
    ("POST", f"{API}/sources/{SOURCE}/retry", None),
    ("POST", f"{API}/sources/{SOURCE}/withdraw", {"reason": "r"}),
    (
        "POST",
        f"{API}/sources/{SOURCE}/takedown",
        {"reference": "TD-1", "requested_on": "2026-10-20"},
    ),
    ("GET", f"{API}/takedowns", None),
    ("GET", f"{API}/sites", None),
    (
        "POST",
        f"{API}/sites",
        {
            "start_url": ROOT + "/",
            "name": "n",
            "publisher": "p",
            "licence_basis": "l",
            "tags": ["sample-web"],
        },
    ),
    ("GET", f"{API}/sites/{SITE}", None),
    ("POST", f"{API}/sites/{SITE}/approve", {}),
    ("POST", f"{API}/sites/{SITE}/reject", {"note": "no"}),
    (
        "PUT",
        f"{API}/sites/{SITE}/settings",
        {"allow_patterns": [], "deny_patterns": [], "schedule": "none", "max_pages": 5},
    ),
    ("PUT", f"{API}/sites/{SITE}/special-category-allow", {"patterns": []}),
    ("POST", f"{API}/sites/{SITE}/crawl", None),
    ("POST", f"{API}/sites/{SITE}/withdraw", {"reason": "r"}),
    ("POST", f"{API}/sites/{SITE}/reinstate", {"note": "n"}),
    ("POST", f"{API}/sources/{SOURCE}/restore", None),
    ("GET", f"{API}/tags", None),
    ("POST", f"{API}/tags/sync", None),
]
# A multipart proposal is a separate shape.
PROPOSAL = {
    "title": "Tidewater Offshore Wind Outlook 2026",
    "publisher": "Fictional Institute for Coastal Energy",
    "licence_basis": "publisher-terms",
    "tags": "sample-reports",
    "canonical_url": "https://example.org/tidewater-2026.pdf",
    "published_on": "2026-03-01",
}


class RagflowClients:
    """``RagflowClient.from_settings`` for the tag sync: the test's fake RAGFlow."""

    def __init__(self, fake: Any) -> None:
        self.fake = fake

    def __call__(self, _settings: Any) -> RagflowClients:
        return self

    async def __aenter__(self) -> Any:
        return self.fake

    async def __aexit__(self, *_: object) -> None:
        return None


class Console:
    def __init__(self, auth: Auth, e: Env) -> None:
        self.auth = auth
        self.e = e
        self.site = Site(
            {
                "/": html("Home", "Welcome").replace(
                    "</main>", "<a href='/a'>A</a><a href='/report'>R</a></main>"
                ),
                "/a": html("Page A", "Alpha"),
                "/report": html("A synthetic web report", "Synthetic report"),
            }
        )
        self.clock = Clock()
        state = auth.app.state
        files = state.settings.models.files.model_copy(update={"content_root": e.content_root})
        ragflow = state.settings.models.ragflow.model_copy(
            update={"admin_ui_url": "http://127.0.0.1:8080"}
        )
        state.settings.models = state.settings.models.model_copy(
            update={"files": files, "ragflow": ragflow}
        )
        state.content_resolve = resolver(PUBLIC)
        state.content_connect = self.site.transport
        state.content_ragflow = RagflowClients(e.fake)

    def as_user(self, email: str, tenant_id: UUID = INTERNAL_TENANT_ID) -> httpx.AsyncClient:
        browser = self.auth.browser()
        token = sign(self.auth.idp.key, email=email, tenant_id=tenant_id)
        browser.headers["Authorization"] = f"Bearer {token}"
        return browser

    def editor(self) -> httpx.AsyncClient:
        return self.as_user(EDITOR_EMAIL)

    async def roles(self, *roles: str) -> None:
        await content_user(self.auth.admin, *roles)

    async def run_jobs(self) -> None:
        context = worker.Context(
            factory=self.e.factory,
            client=self.e.fake,  # type: ignore[arg-type]
            tags=TAGS,
            content_root=self.e.content_root,
            parse_poll_interval=0,
            connect=self.site.transport,
            limiter=HostLimiter(clock=lambda: self.clock.now, sleep=self.clock.sleep),
            resolve=resolver(PUBLIC),
        )
        registry = worker.handlers(context)
        while await worker.run_once(self.e.factory, registry):
            pass

    async def propose(
        self,
        client: httpx.AsyncClient,
        content: bytes | None = None,
        name: str = "tidewater-offshore-wind-2026.pdf",
        licence: bytes | None = None,
        **fields: Any,
    ) -> httpx.Response:
        files: dict[str, Any] = {}
        if content is not None:
            files["file"] = (name, content, "application/octet-stream")
        if licence is not None:
            files["licence_file"] = ("permission-letter.pdf", licence, "application/pdf")
        data = {**PROPOSAL, **fields}
        return await client.post(f"{API}/sources", data=data, files=files or None)

    async def events(self, event: str, key: str, value: str) -> list[dict[str, Any]]:
        rows = await self.auth.admin.fetch(
            "SELECT actor_user_id, metadata FROM audit_events WHERE event = $1 "
            "AND tenant_id = $2 AND metadata->>$3 = $4 ORDER BY created_at, id",
            event,
            INTERNAL_TENANT_ID,
            key,
            value,
        )
        return [{"actor": r["actor_user_id"], **json.loads(r["metadata"])} for r in rows]


@pytest.fixture
async def console(auth: Auth, env: tuple[Env, Ingest], redis: FakeRedis) -> AsyncIterator[Console]:
    e, _ = env
    yield Console(auth, e)
    await auth.admin.execute("DELETE FROM conversations")


# --- who can reach the console -----------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_tenant_admins_and_users_cannot_reach_any_content_route(
    console: Console, method: str, path: str, body: dict[str, Any] | None
) -> None:
    for role in ("tenant_admin", "user"):
        tenant: Tenant = await console.auth.tenant(role=role)
        browser = console.as_user(tenant.email, tenant.id)
        assert (await browser.get("/api/v1/me")).status_code == 200  # a valid session
        response = await browser.request(method, path, json=body)
        assert response.status_code == 403, (role, path)
        assert response.json() == {"detail": "forbidden"}


async def test_the_proposal_upload_is_refused_to_client_tenants(console: Console) -> None:
    tenant: Tenant = await console.auth.tenant(role="tenant_admin")
    response = await console.propose(console.as_user(tenant.email, tenant.id), PDF.read_bytes())
    assert response.status_code == 403
    assert await console.auth.admin.fetchval("SELECT count(*) FROM sources") == 0
    assert not console.e.content_root.exists()  # nothing staged either


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_an_internal_user_without_a_content_role_is_refused(
    console: Console, method: str, path: str, body: dict[str, Any] | None
) -> None:
    browser = console.as_user("analyst@example.org")
    assert (await browser.request(method, path, json=body)).status_code == 403


async def test_unauthenticated_gets_401(console: Console) -> None:
    assert (await console.auth.browser().get(f"{API}/sources")).status_code == 401


# --- what each role may do -----------------------------------------------------------------


async def test_an_editor_proposes_but_cannot_approve(console: Console) -> None:
    await console.roles("content_editor")
    editor = console.editor()
    me = (await editor.get(f"{API}/me")).json()
    assert me == {"roles": ["content_editor"], "ragflow_ui_url": "http://127.0.0.1:8080"}
    response = await console.propose(editor, PDF.read_bytes())
    assert response.status_code == 201, response.text
    source_id = response.json()["source_id"]
    for method, path, body in (
        ("POST", f"{API}/sources/{source_id}/approve", {}),
        ("POST", f"{API}/sources/{source_id}/reject", {"note": "no"}),
        ("POST", f"{API}/sources/{source_id}/retry", None),
        ("POST", f"{API}/sources/{source_id}/withdraw", {"reason": "r"}),
        (
            "POST",
            f"{API}/sources/{source_id}/takedown",
            {"reference": "TD-1", "requested_on": "2026-10-20"},
        ),
        ("POST", f"{API}/tags/sync", None),
    ):
        assert (await editor.request(method, path, json=body)).status_code == 403, path
    row = await console.auth.admin.fetchrow("SELECT * FROM sources WHERE id = $1", UUID(source_id))
    assert (row["status"], row["approved_by"]) == ("proposed", None)
    assert console.e.fake.uploads == []  # nothing reached RAGFlow


async def test_a_reviewer_cannot_propose(console: Console) -> None:
    await console.roles("content_reviewer")
    response = await console.propose(console.editor(), PDF.read_bytes())
    assert response.status_code == 403
    assert not console.e.content_root.exists()


# --- the register: propose, review, status --------------------------------------------------


async def test_propose_approve_and_follow_a_source_audited_and_without_text(
    console: Console, capsys: pytest.CaptureFixture[str]
) -> None:
    await console.roles("content_editor", "content_reviewer")
    client = console.editor()
    proposed = await console.propose(client, PDF.read_bytes())
    assert proposed.status_code == 201, proposed.text
    body = proposed.json()
    assert (body["outcome"], body["status"], body["possible_replacements"]) == (
        "proposed",
        "proposed",
        [],
    )
    source_id = body["source_id"]

    approved = await client.post(f"{API}/sources/{source_id}/approve", json={"note": "fine"})
    assert approved.status_code == 200, approved.text
    await console.run_jobs()

    detail = (await client.get(f"{API}/sources/{source_id}")).json()
    assert (detail["status"], detail["review_note"], detail["chunk_count"]) == (
        "ingested",
        "fine",
        3,
    )
    assert (detail["proposed_by"], detail["approved_by"]) == (EDITOR_EMAIL, EDITOR_EMAIL)
    assert [h["event"] for h in detail["history"]] == [
        "source.proposed",
        "source.approved",
        "source.ingested",
    ]
    assert detail["history"][1]["actor"] == EDITOR_EMAIL
    assert [(j["type"], j["status"]) for j in detail["jobs"]] == [("ingest_source", "succeeded")]
    [link] = [d for d in detail["documents"] if d["tag"] == "sample-reports"]
    assert link["ragflow_url"].startswith("http://127.0.0.1:8080/")  # loopback admin UI
    assert link["document_id"] in link["ragflow_url"]
    # Logs carry identifiers and codes only: no title, no file name.
    logged = capsys.readouterr().out
    assert "Tidewater" not in logged and "tidewater-offshore" not in logged
    # Audited: the proposal and the approval in the editor's (and reviewer's) name.
    [event] = await console.events("source.approved", "source_id", source_id)
    assert event["actor"] == console.e.user_id and event["self_approval"] is True


async def test_the_console_never_returns_document_text(console: Console) -> None:
    await console.roles("content_editor", "content_reviewer")
    client = console.editor()
    sentence = "The synthetic marker sentence about kelp farming yields"
    proposed = await console.propose(
        client,
        f"# Kelp note\n\n{sentence} in 2031.\n".encode(),
        name="kelp.md",
        title="Kelp note",
        tags="sample-web",
        canonical_url="https://example.org/kelp",
    )
    source_id = proposed.json()["source_id"]
    await client.post(f"{API}/sources/{source_id}/approve", json={})
    await console.run_jobs()
    for path in (f"{API}/sources", f"{API}/sources/{source_id}", f"{API}/takedowns"):
        response = await client.get(path)
        assert response.status_code == 200
        assert sentence not in response.text and "kelp.md" not in response.text
    assert "Kelp note" in (await client.get(f"{API}/sources/{source_id}")).text  # the title


async def test_list_filters_by_status_tag_type_and_publisher(console: Console) -> None:
    await console.roles("content_editor", "content_reviewer")
    client = console.editor()
    first = (await console.propose(client, PDF.read_bytes())).json()["source_id"]
    second = await console.propose(
        client,
        b"# Synthetic note\n\nA short synthetic note.\n",
        name="note.md",
        tags="sample-web",
        publisher="Synthetic Web Desk",
        canonical_url="https://example.org/note",
    )
    second_id = second.json()["source_id"]
    await client.post(f"{API}/sources/{second_id}/reject", json={"note": "out of scope"})

    async def ids(**params: str) -> set[str]:
        response = await client.get(f"{API}/sources", params=params)
        assert response.status_code == 200
        return {s["id"] for s in response.json()}

    assert await ids() == {first, second_id}
    assert await ids(status="rejected") == {second_id}
    assert await ids(tag="sample-reports") == {first}
    assert await ids(type="markdown") == {second_id}
    assert await ids(publisher="web desk") == {second_id}  # part of the name, any case
    assert await ids(publisher="%") == set()  # no wildcard injection


async def test_a_possible_replacement_is_flagged_and_needs_the_reviewers_choice(
    console: Console,
) -> None:
    """Same canonical link, another title: flagged for the reviewer (decisions 4 and 3)."""
    await console.roles("content_editor", "content_reviewer")
    client = console.editor()
    first = (await console.propose(client, PDF.read_bytes())).json()["source_id"]
    await client.post(f"{API}/sources/{first}/approve", json={})
    await console.run_jobs()

    response = await console.propose(
        client, PDF.read_bytes() + b"\n% revised", title="Synthetic Outlook, revised edition"
    )
    body = response.json()
    assert body["replaces"] is None
    assert [r["id"] for r in body["possible_replacements"]] == [first]
    second = body["source_id"]
    listed = {s["id"]: s for s in (await client.get(f"{API}/sources")).json()}
    assert listed[second]["possible_replacement"] is True
    assert listed[first]["possible_replacement"] is False
    detail = (await client.get(f"{API}/sources/{second}")).json()
    assert [r["title"] for r in detail["possible_replacements"]] == [PROPOSAL["title"]]

    refused = await client.post(f"{API}/sources/{second}/approve", json={})
    assert (refused.status_code, refused.json()["detail"]) == (422, "replacement_choice_required")
    ok = await client.post(f"{API}/sources/{second}/approve", json={"replaces": first})
    assert ok.status_code == 200
    await console.run_jobs()
    detail = (await client.get(f"{API}/sources/{second}")).json()
    assert detail["supersedes"]["id"] == first
    assert (await client.get(f"{API}/sources/{first}")).json()["status"] == "withdrawn"


async def test_the_same_link_and_title_replace_without_a_choice(console: Console) -> None:
    """Owner decision 3 (Oct 23, 2026, P1c-14): a new file with the canonical link and the
    title of an ingested source replaces it; the console says so and flags nothing."""
    await console.roles("content_editor", "content_reviewer")
    client = console.editor()
    first = (await console.propose(client, PDF.read_bytes())).json()["source_id"]
    await client.post(f"{API}/sources/{first}/approve", json={})
    await console.run_jobs()

    title = f"  {PROPOSAL['title'].upper()} "  # case and spacing do not matter
    body = (await console.propose(client, PDF.read_bytes() + b"\n% revised", title=title)).json()
    second = body["source_id"]
    assert body["possible_replacements"] == [] and body["replaces"]["id"] == first
    listed = {s["id"]: s for s in (await client.get(f"{API}/sources")).json()}
    assert listed[second]["possible_replacement"] is False
    detail = (await client.get(f"{API}/sources/{second}")).json()
    assert (detail["supersedes"]["id"], detail["possible_replacements"]) == (first, [])

    ok = await client.post(f"{API}/sources/{second}/approve", json={})
    assert ok.status_code == 200, ok.text
    await console.run_jobs()
    assert (await client.get(f"{API}/sources/{first}")).json()["status"] == "withdrawn"
    [approval] = await console.events("source.approved", "source_id", second)
    assert (approval["replaces"], approval["method"]) == (first, "same_link_and_title")


async def test_downloadable_needs_no_letter_and_an_attached_letter_is_kept(
    console: Console,
) -> None:
    """Decision 10 (Oct 22, 2026): a downloadable third-party file needs its licence basis,
    not a permission letter; a letter may still be attached."""
    await console.roles("content_editor", "content_reviewer")
    client = console.editor()
    variant = PDF.read_bytes() + b"\n% synthetic variant\n"
    without = await console.propose(client, variant, downloadable="true")
    assert without.status_code == 201, without.text
    detail = (await client.get(f"{API}/sources/{without.json()['source_id']}")).json()
    assert (detail["downloadable"], detail["licence_file"]) == (True, False)
    no_basis = await console.propose(
        client, PDF.read_bytes(), downloadable="true", licence_basis=""
    )
    assert no_basis.status_code == 422
    letter = b"%PDF-1.4 synthetic permission letter"
    response = await console.propose(client, PDF.read_bytes(), downloadable="true", licence=letter)
    assert response.status_code == 201, response.text
    source_id = response.json()["source_id"]
    detail = (await client.get(f"{API}/sources/{source_id}")).json()
    assert (detail["downloadable"], detail["licence_file"]) == (True, True)
    download = await client.get(f"{API}/sources/{source_id}/licence")
    assert download.status_code == 200 and download.content == letter
    assert download.headers["content-disposition"].endswith(f'licence-{source_id}.pdf"')
    # Own work may be downloadable without a letter.
    own = await console.propose(
        client,
        PDF.read_bytes() + b"\n% own",
        downloadable="true",
        licence_basis="own-work",
        canonical_url="https://example.org/own",
    )
    assert own.status_code == 201, own.text
    # A letter can be attached later, audited.
    attach = await client.put(
        f"{API}/sources/{own.json()['source_id']}/licence",
        files={"licence_file": ("letter.txt", b"synthetic letter", "text/plain")},
    )
    assert attach.status_code == 204
    [event] = await console.events("source.licence_file_set", "source_id", own.json()["source_id"])
    assert event["status"] == "added"


async def test_a_url_is_proposed_from_a_public_host_only(console: Console) -> None:
    await console.roles("content_editor")
    client = console.editor()
    response = await console.propose(
        client, None, url=ROOT + "/report", canonical_url="", tags="sample-web"
    )
    assert response.status_code == 201, response.text
    row = await console.auth.admin.fetchrow(
        "SELECT type, canonical_url FROM sources WHERE id = $1",
        UUID(response.json()["source_id"]),
    )
    assert (row["type"], row["canonical_url"]) == ("html", ROOT + "/report")
    console.auth.app.state.content_resolve = resolver({"site.example": ["10.0.0.9"]})
    refused = await console.propose(client, None, url=ROOT + "/other", tags="sample-web")
    assert (refused.status_code, refused.json()["detail"]) == (422, "not_public")
    both = await console.propose(client, PDF.read_bytes(), url=ROOT + "/report")
    assert (both.status_code, both.json()["detail"]) == (422, "file_or_url")


async def test_reject_withdraw_and_the_takedown_queue(console: Console) -> None:
    await console.roles("content_editor", "content_reviewer")
    client = console.editor()
    source_id = (await console.propose(client, PDF.read_bytes())).json()["source_id"]
    empty = await client.post(f"{API}/sources/{source_id}/reject", json={"note": ""})
    assert empty.status_code == 422
    await client.post(f"{API}/sources/{source_id}/approve", json={})
    await console.run_jobs()

    takedown = await client.post(
        f"{API}/sources/{source_id}/takedown",
        json={"reference": "TD-2026-9", "requested_on": date.today().isoformat()},
    )
    assert takedown.status_code == 200, takedown.text
    assert takedown.json()["working_days_left"] == 10
    queue = (await client.get(f"{API}/takedowns")).json()
    assert [(q["source_id"], q["reference"], q["licence_grounds"]) for q in queue] == [
        (source_id, "TD-2026-9", False)
    ]
    future = await client.post(
        f"{API}/sources/{source_id}/takedown",
        json={"reference": "TD-X", "requested_on": "2999-01-01"},
    )
    assert future.status_code == 422

    withdrawn = await client.post(
        f"{API}/sources/{source_id}/withdraw", json={"reason": "takedown"}
    )
    assert withdrawn.status_code == 200
    await console.run_jobs()
    assert (await client.get(f"{API}/takedowns")).json() == []
    detail = (await client.get(f"{API}/sources/{source_id}")).json()
    assert (detail["status"], detail["withdrawal_reason"]) == ("withdrawn", "takedown")
    again = await client.post(f"{API}/sources/{source_id}/withdraw", json={"reason": "again"})
    assert (again.status_code, again.json()["detail"]) == (409, "not_withdrawable")
    events = [
        e["event"] for e in (await client.get(f"{API}/sources/{source_id}")).json()["history"]
    ]
    assert "source.takedown_recorded" in events and "source.withdrawn" in events
    assert (await client.get(f"{API}/sources/{uuid.uuid4()}")).status_code == 404


async def test_the_console_shows_a_failure_as_a_code_never_ragflows_text(
    console: Console,
) -> None:
    """P2A-13: a parse failure shows its code; a row written before P2A-13 with
    RAGFlow's text shows the audited code instead."""
    from tests.ragflow_fake import Outcome

    await console.roles("content_editor", "content_reviewer")
    client = console.editor()
    console.e.fake.outcomes[".pdf"] = Outcome(
        run="FAIL", chunk_count=0, progress_msg="[ERROR] Synthetic secret body text"
    )
    source_id = (await console.propose(client, PDF.read_bytes())).json()["source_id"]
    await client.post(f"{API}/sources/{source_id}/approve", json={})
    await console.run_jobs()
    detail = (await client.get(f"{API}/sources/{source_id}")).json()
    assert detail["status"] == "failed"
    assert detail["error"] == "parse_failed: sample-reports FAIL"
    # A row from before P2A-13 still holding RAGFlow's message text.
    legacy = "RAGFlow get_document failed (code 102): Synthetic secret body text"
    await console.auth.admin.execute(
        "UPDATE sources SET error = $2 WHERE id = $1", UUID(source_id), legacy
    )
    shown = (await client.get(f"{API}/sources/{source_id}")).json()["error"]
    assert shown == "parse_failed"
    assert "secret" not in json.dumps((await client.get(f"{API}/sources/{source_id}")).json())


async def test_the_takedown_clock_follows_the_configured_calendar(console: Console) -> None:
    """P2A-12 (b): the route takes the due date and the SLA timer from the startup
    calendar (``Settings.holidays``), not from a default."""
    from app.content.register import TakedownItem
    from app.core.holidays import HolidayCalendar

    await console.roles("content_editor", "content_reviewer")
    client = console.editor()
    source_id = (await console.propose(client, PDF.read_bytes())).json()["source_id"]
    await client.post(f"{API}/sources/{source_id}/approve", json={})
    await console.run_jobs()
    # Tue Oct 20, 2026; a synthetic holiday on Wed Oct 21.
    holiday = date(2026, 10, 21)
    console.auth.app.state.settings.holidays = HolidayCalendar("test", frozenset({holiday}))
    recorded = await client.post(
        f"{API}/sources/{source_id}/takedown",
        json={"reference": "TD-2026-12", "requested_on": "2026-10-20"},
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["due_on"] == "2026-11-04"  # Nov 3 without the holiday
    item = TakedownItem(uuid.uuid4(), "ingested", "TD", date(2026, 10, 20), date(2026, 11, 4))
    left = item.working_days_left(date.today(), {holiday})
    [queued] = (await client.get(f"{API}/takedowns")).json()
    assert (queued["due_on"], queued["working_days_left"]) == ("2026-11-04", left)
    detail = (await client.get(f"{API}/sources/{source_id}")).json()
    assert detail["takedown"]["working_days_left"] == left


# --- sites ---------------------------------------------------------------------------------


async def test_sites_are_registered_reviewed_crawled_and_shown_with_their_pages(
    console: Console,
) -> None:
    await console.roles("content_editor")
    editor = console.editor()
    created = await editor.post(
        f"{API}/sites",
        json={
            "start_url": ROOT + "/",
            "name": "Synthetic Energy Institute",
            "publisher": "Synthetic Energy Institute",
            "licence_basis": "publisher-terms",
            "tags": ["sample-web"],
            "deny_patterns": ["/report"],
            "schedule": "weekly",
            "max_pages": 10,
        },
    )
    assert created.status_code == 201, created.text
    site_id = created.json()["id"]
    assert created.json()["status"] == "proposed"
    duplicate = await editor.post(
        f"{API}/sites",
        json={
            "start_url": ROOT + "/",
            "name": "x",
            "publisher": "x",
            "licence_basis": "x",
            "tags": ["sample-web"],
        },
    )
    assert duplicate.status_code == 409
    assert (await editor.post(f"{API}/sites/{site_id}/approve", json={})).status_code == 403

    await console.roles("content_editor", "content_reviewer")
    assert (await editor.post(f"{API}/sites/{site_id}/approve", json={})).status_code == 200
    await console.run_jobs()
    detail = (await editor.get(f"{API}/sites/{site_id}")).json()
    assert (detail["status"], detail["allow_decision"], detail["page_count"]) == (
        "approved",
        "allowed",
        2,
    )
    assert {p["url"]: p["state"] for p in detail["pages"]} == {
        ROOT + "/": "live",
        ROOT + "/a": "live",
    }
    assert detail["deny_patterns"] == ["/report"]
    assert [j["type"] for j in detail["jobs"]] == ["crawl_site"]
    listed = (await editor.get(f"{API}/sites")).json()
    assert [(s["id"], s["blocked_count"]) for s in listed] == [(site_id, 0)]
    sources = (await editor.get(f"{API}/sources", params={"site_id": site_id})).json()
    assert len(sources) == 2

    settings = await editor.put(
        f"{API}/sites/{site_id}/settings",
        json={"allow_patterns": [], "deny_patterns": [], "schedule": "monthly", "max_pages": 20},
    )
    assert settings.status_code == 204
    whitelist = await editor.put(
        f"{API}/sites/{site_id}/special-category-allow", json={"patterns": ["/health/*"]}
    )
    assert whitelist.status_code == 204
    bad = await editor.put(
        f"{API}/sites/{site_id}/special-category-allow", json={"patterns": ["health"]}
    )
    assert (bad.status_code, bad.json()["detail"]) == (422, "bad_pattern")
    # Any content role may ask for a crawl now: here a second internal user, an editor.
    analyst = await console.auth.admin.fetchval(
        "SELECT id FROM users WHERE tenant_id = $1 AND email = 'analyst@example.org'",
        INTERNAL_TENANT_ID,
    )
    await console.auth.admin.execute(
        "INSERT INTO content_roles (user_id, role) VALUES ($1, 'content_editor')", analyst
    )
    try:
        other = console.as_user("analyst@example.org")
        assert (await other.post(f"{API}/sites/{site_id}/crawl")).status_code == 200
        assert (await other.post(f"{API}/sites/{site_id}/approve", json={})).status_code == 403
    finally:
        await console.auth.admin.execute("DELETE FROM content_roles WHERE user_id = $1", analyst)
    await console.run_jobs()
    detail = (await editor.get(f"{API}/sites/{site_id}")).json()
    assert (detail["schedule"], detail["special_category_allow"]) == ("monthly", ["/health/*"])
    assert {p["url"] for p in detail["pages"]} == {ROOT + "/", ROOT + "/a", ROOT + "/report"}
    for event in ("site.proposed", "site.approved", "site.settings_changed", "site.crawled"):
        assert await console.events(event, "site_id", site_id), event


async def test_a_reviewer_withdraws_a_site_and_restores_a_page_from_the_console(
    console: Console,
) -> None:
    """P1c-14: "withdraw site" and "restore" are reviewer actions, audited."""
    await console.roles("content_editor", "content_reviewer")
    editor = console.editor()
    created = await editor.post(
        f"{API}/sites",
        json={
            "start_url": ROOT + "/",
            "name": "Synthetic Energy Institute",
            "publisher": "Synthetic Energy Institute",
            "licence_basis": "publisher-terms",
            "tags": ["sample-web"],
            "schedule": "weekly",
        },
    )
    site_id = created.json()["id"]
    assert (await editor.post(f"{API}/sites/{site_id}/approve", json={})).status_code == 200
    await console.run_jobs()
    pages = (await editor.get(f"{API}/sources", params={"site_id": site_id})).json()
    page = next(p for p in pages if p["canonical_url"] == ROOT + "/a")
    withdrawn = await editor.post(
        f"{API}/sources/{page['id']}/withdraw", json={"reason": "licence check"}
    )
    assert withdrawn.status_code == 200
    await console.run_jobs()

    await console.roles("content_editor")
    assert (await editor.post(f"{API}/sources/{page['id']}/restore")).status_code == 403
    refused = await editor.post(f"{API}/sites/{site_id}/withdraw", json={"reason": "stop"})
    assert refused.status_code == 403
    await console.roles("content_editor", "content_reviewer")
    restored = await editor.post(f"{API}/sources/{page['id']}/restore")
    assert restored.status_code == 204, restored.text
    again = await editor.post(f"{API}/sources/{page['id']}/restore")
    assert (again.status_code, again.json()["detail"]) == (409, "not_a_withdrawn_page")
    detail = (await editor.get(f"{API}/sites/{site_id}")).json()
    assert {p["url"]: (p["state"], p["reason"]) for p in detail["pages"]}[ROOT + "/a"] == (
        "removed",
        "restored",
    )

    empty = await editor.post(f"{API}/sites/{site_id}/withdraw", json={"reason": " "})
    assert (empty.status_code, empty.json()["detail"]) == (422, "note_required")
    done = await editor.post(f"{API}/sites/{site_id}/withdraw", json={"reason": "retired"})
    assert done.status_code == 200, done.text
    assert len(done.json()["job_ids"]) == len(pages) - 1  # every page but the withdrawn one
    await console.run_jobs()
    detail = (await editor.get(f"{API}/sites/{site_id}")).json()
    assert (detail["status"], detail["next_crawl_at"]) == ("withdrawn", None)
    assert (detail["withdrawal_reason"], detail["withdrawn_at"] is not None) == ("retired", True)
    assert "live" not in {p["state"] for p in detail["pages"]}
    sources = (await editor.get(f"{API}/sources", params={"site_id": site_id})).json()
    assert {s["status"] for s in sources} == {"withdrawn"}
    crawl = await editor.post(f"{API}/sites/{site_id}/crawl")
    assert (crawl.status_code, crawl.json()["detail"]) == (409, "not_approved")
    twice = await editor.post(f"{API}/sites/{site_id}/withdraw", json={"reason": "retired"})
    assert (twice.status_code, twice.json()["detail"]) == (409, "already_withdrawn")
    assert await console.events("site.withdrawn", "site_id", site_id)
    assert await console.events("source.restored", "source_id", page["id"])


async def test_a_reviewer_reinstates_a_withdrawn_site_from_the_console(console: Console) -> None:
    """P2A-12 (a): "reinstate" is a reviewer action with a required note; the site comes
    back proposed, for a fresh approval, never approved."""
    await console.roles("content_editor", "content_reviewer")
    editor = console.editor()
    created = await editor.post(
        f"{API}/sites",
        json={
            "start_url": ROOT + "/",
            "name": "Synthetic Energy Institute",
            "publisher": "Synthetic Energy Institute",
            "licence_basis": "publisher-terms",
            "tags": ["sample-web"],
        },
    )
    site_id = created.json()["id"]
    assert (await editor.post(f"{API}/sites/{site_id}/approve", json={})).status_code == 200
    await console.run_jobs()
    early = await editor.post(f"{API}/sites/{site_id}/reinstate", json={"note": "back"})
    assert (early.status_code, early.json()["detail"]) == (409, "not_withdrawn")
    withdrawn = await editor.post(f"{API}/sites/{site_id}/withdraw", json={"reason": "retired"})
    assert withdrawn.status_code == 200
    running = await editor.post(f"{API}/sites/{site_id}/reinstate", json={"note": "back"})
    assert (running.status_code, running.json()["detail"]) == (409, "withdrawal_running")
    await console.run_jobs()

    await console.roles("content_editor")
    refused = await editor.post(f"{API}/sites/{site_id}/reinstate", json={"note": "back"})
    assert refused.status_code == 403
    await console.roles("content_editor", "content_reviewer")
    assert (await editor.post(f"{API}/sites/{site_id}/reinstate", json={})).status_code == 422
    blank = await editor.post(f"{API}/sites/{site_id}/reinstate", json={"note": " "})
    assert (blank.status_code, blank.json()["detail"]) == (422, "note_required")
    unknown = await editor.post(f"{API}/sites/{site_id}/reinstate", json={"note": "b", "x": 1})
    assert unknown.status_code == 422  # no other field is accepted
    done = await editor.post(f"{API}/sites/{site_id}/reinstate", json={"note": "agreed again"})
    assert done.status_code == 200, done.text
    assert done.json() == {"released": 3, "kept_blocked": 0}
    detail = (await editor.get(f"{API}/sites/{site_id}")).json()
    assert (detail["status"], detail["approved_by"], detail["next_crawl_at"]) == (
        "proposed",
        None,
        None,
    )
    assert (detail["start_url"], detail["review_note"]) == (ROOT + "/", "agreed again")
    crawl = await editor.post(f"{API}/sites/{site_id}/crawl")
    assert (crawl.status_code, crawl.json()["detail"]) == (409, "not_approved")
    assert await console.events("site.reinstated", "site_id", site_id)
    assert (await editor.post(f"{API}/sites/{site_id}/approve", json={})).status_code == 200
    await console.run_jobs()
    sources = (await editor.get(f"{API}/sources", params={"site_id": site_id})).json()
    assert sorted(s["status"] for s in sources) == ["ingested"] * 3 + ["withdrawn"] * 3


# --- tags ----------------------------------------------------------------------------------


async def test_tags_show_the_mapping_and_a_reviewer_syncs_it(console: Console) -> None:
    await console.roles("content_editor")
    client = console.editor()
    tags = {t["tag"]: t for t in (await client.get(f"{API}/tags")).json()}
    assert set(tags) == set(TAGS)
    web = tags["sample-web"]
    assert web["dataset_id"] == console.e.datasets["sample-web"]
    assert web["ragflow_url"] == (
        "http://127.0.0.1:8080/dataset/dataset/" + console.e.datasets["sample-web"]
    )
    assert (await client.post(f"{API}/tags/sync")).status_code == 403

    await console.roles("content_editor", "content_reviewer")
    synced = await client.post(f"{API}/tags/sync")
    assert synced.status_code == 200, synced.text
    assert {r["tag"] for r in synced.json()} == set(TAGS)
    rows = await console.auth.admin.fetch(
        "SELECT metadata FROM audit_events WHERE event = 'content.datasets_synced' "
        "AND actor_user_id = $1",
        console.e.user_id,
    )
    assert rows and json.loads(rows[-1]["metadata"])["count"] == len(TAGS)


async def test_the_ragflow_link_is_absent_without_an_admin_url(console: Console) -> None:
    await console.roles("content_editor")
    state = console.auth.app.state
    ragflow = state.settings.models.ragflow.model_copy(update={"admin_ui_url": None})
    state.settings.models = state.settings.models.model_copy(update={"ragflow": ragflow})
    tags = (await console.editor().get(f"{API}/tags")).json()
    assert {t["ragflow_url"] for t in tags} == {None}
