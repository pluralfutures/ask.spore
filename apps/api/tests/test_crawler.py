"""P0-10: the crawler against a fake site (httpx.MockTransport)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app import cli
from app.content.crawler import CrawlReport, Page, crawl, normalise, page_file_name, write_pages
from app.content.fetch import USER_AGENT
from app.content.ingest import IngestResult
from app.core.config import load_settings
from tests.test_datasets_sync import ENV

ROOT = "https://site.example"


def html(title: str, body: str, head: str = "") -> str:
    paragraphs = " ".join(f"{body} sentence {n} with enough words to count." for n in range(8))
    return (
        f"<html><head><title>{title}</title>{head}</head><body>"
        f"<nav><a href='/'>Home</a></nav><main><h1>{title}</h1><p>{paragraphs}</p></main>"
        f"<footer>footer text</footer></body></html>"
    )


class Site:
    def __init__(self, pages: dict[str, Any]) -> None:
        # path -> body (str) or (status, headers, body)
        self.pages = pages
        self.requested: list[str] = []
        self.user_agents: set[str] = set()

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.raw_path.decode()
            self.requested.append(path)
            self.user_agents.add(request.headers.get("user-agent", ""))
            if request.url.host != "site.example":
                return httpx.Response(200, html=html("Elsewhere", "off-site"))
            entry = self.pages.get(path)
            if entry is None:
                return httpx.Response(404, text="not found")
            if isinstance(entry, str):
                return httpx.Response(200, html=entry)
            status, headers, body = entry
            return httpx.Response(status, headers=headers, content=body.encode())

        return httpx.MockTransport(handler)


async def run(site: Site, start: str = ROOT + "/", max_pages: int = 10) -> CrawlReport:
    delays: list[float] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    async with httpx.AsyncClient(
        transport=site.transport(), headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as http:
        report = await crawl(http, start, max_pages, sleep=sleep)
    report.delays = delays  # type: ignore[attr-defined]
    return report


def three_page_site(**extra: Any) -> dict[str, Any]:
    pages: dict[str, Any] = {
        "/": html("Home", "Welcome", "")
        .replace("</main>", "<a href='/a?utm_source=x#top'>A</a><a href='/b'>B</a></main>")
        .replace("</main>", "<a href='https://other.example/x'>Out</a></main>")
        .replace("</main>", "<a href='/report.pdf'>PDF</a></main>"),
        "/a": html("Page A", "Alpha"),
        "/b": html("Page B", "Beta"),
    }
    pages.update(extra)
    return pages


async def test_crawls_same_host_pages_and_renders_markdown() -> None:
    site = Site(three_page_site())
    report = await run(site)

    assert report.status == "ok"
    assert [p.url for p in report.pages] == [ROOT + "/", ROOT + "/a", ROOT + "/b"]
    page_a = report.pages[1]
    assert page_a.title == "Page A"
    assert "Alpha sentence 0" in page_a.markdown
    assert "footer text" not in page_a.markdown  # readable content only
    assert "/report.pdf" not in site.requested  # non-HTML links are not crawled
    assert all(not p.startswith("/x") for p in site.requested)  # same host only
    assert site.user_agents == {USER_AGENT}


async def test_robots_disallow_is_honoured() -> None:
    robots = "User-agent: *\nDisallow: /b\n"
    site = Site(three_page_site(**{"/robots.txt": (200, {}, robots)}))
    report = await run(site)
    assert report.status == "ok"
    assert [p.url for p in report.pages] == [ROOT + "/", ROOT + "/a"]
    assert "/b" not in site.requested
    assert report.skipped["robots"] == 1


async def test_robots_disallowing_our_agent_blocks_the_site() -> None:
    robots = "User-agent: ask.spore-crawler\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    site = Site(three_page_site(**{"/robots.txt": (200, {}, robots)}))
    report = await run(site)
    assert report.status == "robots_disallowed"
    assert report.pages == []
    assert site.requested == ["/robots.txt"]


async def test_robots_server_error_means_no_crawl() -> None:
    site = Site(three_page_site(**{"/robots.txt": (503, {}, "down")}))
    report = await run(site)
    assert report.status == "unreachable"
    assert site.requested == ["/robots.txt"]


async def test_crawl_delay_is_respected() -> None:
    robots = "User-agent: *\nCrawl-delay: 5\n"
    site = Site(three_page_site(**{"/robots.txt": (200, {}, robots)}))
    report = await run(site)
    assert report.delays == [5.0, 5.0]  # type: ignore[attr-defined]


async def test_tdm_reservation_header_blocks_the_site() -> None:
    reserved = (200, {"content-type": "text/html", "tdm-reservation": "1"}, html("B", "Beta"))
    site = Site(three_page_site(**{"/b": reserved}))
    report = await run(site)
    assert report.status == "tdm_reserved"
    assert report.pages == []  # nothing from the site is ingested, not even earlier pages


async def test_tdm_reservation_meta_tag_blocks_the_site() -> None:
    head = '<meta name="tdm-reservation" content="1">'
    site = Site(three_page_site(**{"/a": html("A", "Alpha", head)}))
    report = await run(site)
    assert report.status == "tdm_reserved"
    assert report.pages == []


async def test_tdmrep_json_blocks_the_site_before_any_page() -> None:
    rules = json.dumps([{"location": "/*", "tdm-reservation": 1}])
    site = Site(three_page_site(**{"/.well-known/tdmrep.json": (200, {}, rules)}))
    report = await run(site)
    assert report.status == "tdm_reserved"
    assert "/" not in site.requested


async def test_tdmrep_json_without_reservation_allows_crawl() -> None:
    rules = json.dumps([{"location": "/*", "tdm-reservation": 0}])
    site = Site(three_page_site(**{"/.well-known/tdmrep.json": (200, {}, rules)}))
    assert (await run(site)).status == "ok"


@pytest.mark.parametrize(
    ("page", "reason"),
    [
        ((200, {"content-type": "text/html", "x-robots-tag": "noai"}, html("B", "Beta")), "noai"),
        (html("B", "Beta", '<meta name="robots" content="noindex, follow">'), "noindex"),
    ],
)
async def test_noai_and_noindex_pages_are_skipped(page: Any, reason: str) -> None:
    site = Site(three_page_site(**{"/b": page}))
    report = await run(site)
    assert report.status == "ok"
    assert ROOT + "/b" not in [p.url for p in report.pages]
    assert report.skipped["noai_or_noindex"] == 1


async def test_page_budget() -> None:
    report = await run(Site(three_page_site()), max_pages=2)
    assert len(report.pages) == 2


def test_normalise_strips_fragment_and_tracking_parameters() -> None:
    assert (
        normalise("https://Site.example/a?utm_source=x&id=3&fbclid=y#top")
        == "https://site.example/a?id=3"
    )
    assert normalise("https://site.example") == "https://site.example/"


def test_write_pages(tmp_path: Path) -> None:
    pages = [Page(ROOT + "/", "Home", "# Home\n\ntext"), Page(ROOT + "/a/b", "B", "# B\n\nx")]
    paths = write_pages(pages, tmp_path / "out")
    assert [p.name for p in paths] == ["001-index.md", "002-a-b.md"]
    assert paths[0].read_text(encoding="utf-8") == "# Home\n\ntext\n"
    assert page_file_name(pages[1], 7) == "007-a-b.md"


def test_cli_crawl_arguments() -> None:
    args = cli.build_parser().parse_args(
        ["crawl", ROOT, "--tag", "sample-web", "--max-pages", "5", "--licence", "terms ok"]
    )
    assert (args.site_url, args.max_pages, args.tag) == (ROOT, 5, ["sample-web"])
    with pytest.raises(SystemExit):
        cli.main(["crawl", ROOT, "--tag", "sample-web", "--max-pages", "0", "--licence", "x"])


def test_cli_crawl_writes_files_and_ingests_each_page(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    pages = [Page(ROOT + "/", "Home", "# Home\n\nwelcome"), Page(ROOT + "/a", "A", "# A\n\nx")]
    calls: list[tuple[Any, Any]] = []

    async def fake_crawl(*_: Any) -> CrawlReport:
        return CrawlReport("ok", pages=pages)

    async def fake_ingest(_f: Any, _c: Any, _t: Any, source: Any, metadata: Any, **_: Any) -> Any:
        calls.append((source, metadata))
        return IngestResult(source_id=uuid4(), status="ingested", chunk_count=1)

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(cli, "get_settings", lambda: load_settings(environ=ENV))
    monkeypatch.setattr(cli, "crawl", fake_crawl)
    monkeypatch.setattr(cli, "submit", fake_ingest)
    monkeypatch.setattr(cli.RagflowClient, "from_settings", staticmethod(lambda _: Client()))
    out = tmp_path / "pages"
    argv = ["crawl", ROOT, "--tag", "sample-web", "--max-pages", "5", "--licence", "site terms"]
    code = cli.main([*argv, "--out-dir", str(out)])

    assert code == 0
    assert sorted(p.name for p in out.iterdir()) == ["001-index.md", "002-a.md"]
    assert [(s.type, s.filename) for s, _ in calls] == [
        ("markdown", "001-index.md"),
        ("markdown", "002-a.md"),
    ]
    assert [m.canonical_url for _, m in calls] == [ROOT + "/", ROOT + "/a"]
    assert {(m.tags, m.publisher, m.licence_basis) for _, m in calls} == {
        (("sample-web",), "site.example", "site terms")
    }
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["event"] for line in logged] == [
        "crawl.finished",
        "ingest.result",
        "ingest.result",
    ]
    assert all("welcome" not in json.dumps(line) for line in logged)
