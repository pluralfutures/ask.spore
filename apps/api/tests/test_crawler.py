"""P0-10, P1b-04: the crawler engine against a fake site (httpx.MockTransport).

Synthetic pages only. The per-host rate limit runs on a fake clock: every ``sleep`` the
limiter asks for is recorded and moves the clock on."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest

from app import cli
from app.content.crawler import (
    HostLimiter,
    Scope,
    SiteCrawler,
    Visit,
    normalise,
    published_on,
)
from app.content.fetch import (
    USER_AGENT,
    FetchError,
    public_only,
    require_public_url,
)
from app.content.special import special_category, whitelisted

ROOT = "https://site.example"
PUBLIC = "93.184.216.34"


def html(title: str, body: str, head: str = "") -> str:
    paragraphs = " ".join(f"{body} sentence {n} with enough words to count." for n in range(8))
    return (
        f"<html><head><title>{title}</title>{head}</head><body>"
        f"<nav><a href='/'>Home</a></nav><main><h1>{title}</h1><p>{paragraphs}</p></main>"
        f"<footer>footer text</footer></body></html>"
    )


class Site:
    """A fake website: path -> body (str) or (status, headers, body)."""

    def __init__(self, pages: dict[str, Any], host: str = "site.example") -> None:
        self.pages = pages
        self.host = host
        self.requested: list[str] = []
        self.user_agents: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode()
        self.requested.append(path)
        self.user_agents.add(request.headers.get("user-agent", ""))
        if request.url.host != self.host:
            return httpx.Response(200, html=html("Elsewhere", "off-site"))
        entry = self.pages.get(path)
        if entry is None:
            return httpx.Response(404, text="not found")
        if isinstance(entry, str):
            return httpx.Response(200, html=entry)
        status, headers, body = entry
        return httpx.Response(status, headers=headers, content=body.encode())

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport(), headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def limiter(self) -> HostLimiter:
        return HostLimiter(clock=lambda: self.now, sleep=self.sleep)


def no_special(_url: str, _title: str) -> str | None:
    return None


async def run(
    site: Site,
    start: str = ROOT + "/",
    max_pages: int = 10,
    scope: Scope | None = None,
    special: Callable[[str, str], str | None] = no_special,
    clock: Clock | None = None,
) -> tuple[SiteCrawler, list[Visit], Clock]:
    clock = clock or Clock()
    async with site.client() as http:
        crawler = SiteCrawler(
            http,
            start,
            max_pages=max_pages,
            scope=scope or Scope(),
            special=special,
            limiter=clock.limiter(),
        )
        await crawler.check()
        visits = [v async for v in crawler.walk()]
    return crawler, visits, clock


def pages(visits: list[Visit]) -> list[str]:
    return [v.url for v in visits if v.kind == "page"]


def three_page_site(**extra: Any) -> dict[str, Any]:
    site: dict[str, Any] = {
        "/": html("Home", "Welcome", "")
        .replace("</main>", "<a href='/a?utm_source=x#top'>A</a><a href='/b'>B</a></main>")
        .replace("</main>", "<a href='https://other.example/x'>Out</a></main>")
        .replace("</main>", "<a href='/report.pdf'>PDF</a></main>"),
        "/a": html("Page A", "Alpha"),
        "/b": html("Page B", "Beta"),
    }
    site.update(extra)
    return site


async def test_crawls_same_host_pages_and_renders_markdown() -> None:
    site = Site(three_page_site())
    crawler, visits, _ = await run(site)

    assert crawler.status == "ok" and crawler.exhausted
    assert pages(visits) == [ROOT + "/", ROOT + "/a", ROOT + "/b"]
    page_a = visits[1]
    assert page_a.title == "Page A"
    assert "Alpha sentence 0" in page_a.markdown
    assert "footer text" not in page_a.markdown  # readable content only
    assert page_a.raw.startswith(b"<html>")  # the snapshot is the raw HTML
    assert "/report.pdf" not in site.requested  # non-HTML links are not crawled
    assert all(not p.startswith("/x") for p in site.requested)  # same host only
    assert site.user_agents == {USER_AGENT}


async def test_robots_disallow_is_honoured() -> None:
    robots = "User-agent: *\nDisallow: /b\n"
    site = Site(three_page_site(**{"/robots.txt": (200, {}, robots)}))
    crawler, visits, _ = await run(site)
    assert crawler.status == "ok"
    assert pages(visits) == [ROOT + "/", ROOT + "/a"]
    assert "/b" not in site.requested
    assert crawler.skipped["robots"] == 1


async def test_robots_disallowing_our_agent_blocks_the_site() -> None:
    robots = "User-agent: ask.spore-crawler\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    site = Site(three_page_site(**{"/robots.txt": (200, {}, robots)}))
    crawler, visits, _ = await run(site)
    assert crawler.status == "robots_disallowed"
    assert visits == []
    assert site.requested == ["/robots.txt"]


async def test_robots_server_error_means_no_crawl() -> None:
    site = Site(three_page_site(**{"/robots.txt": (503, {}, "down")}))
    crawler, visits, _ = await run(site)
    assert (crawler.status, visits) == ("unreachable", [])
    assert site.requested == ["/robots.txt"]


async def test_crawl_delay_is_respected() -> None:
    robots = "User-agent: *\nCrawl-delay: 5\n"
    site = Site(three_page_site(**{"/robots.txt": (200, {}, robots)}))
    _, visits, clock = await run(site)
    assert len(pages(visits)) == 3
    # robots.txt goes first at the default rate; then every request waits 5 seconds.
    assert clock.sleeps == [1.0, 5.0, 5.0, 5.0]


async def test_the_rate_limit_is_per_host_and_shared_by_crawls() -> None:
    clock = Clock()
    limiter = clock.limiter()
    await limiter.wait("site.example")
    await limiter.wait("other.example")  # another host does not wait
    assert clock.sleeps == []
    await limiter.wait("site.example")
    assert clock.sleeps == [1.0]
    # A second crawl of the same host, with the same worker's limiter, waits its turn.
    site = Site(three_page_site())
    async with site.client() as http:
        crawler = SiteCrawler(
            http, ROOT + "/", max_pages=1, scope=Scope(), special=no_special, limiter=limiter
        )
        await crawler.check()
    assert clock.sleeps == [1.0, 1.0, 1.0]  # robots.txt and tdmrep.json, one second apart


async def test_tdm_reservation_header_blocks_the_site() -> None:
    reserved = (200, {"content-type": "text/html", "tdm-reservation": "1"}, html("B", "Beta"))
    site = Site(three_page_site(**{"/b": reserved}))
    crawler, visits, _ = await run(site)
    assert crawler.status == "tdm_reserved"
    assert visits[-1].reason == "tdm_reserved"


async def test_tdm_reservation_meta_tag_blocks_the_site() -> None:
    head = '<meta name="tdm-reservation" content="1">'
    site = Site(three_page_site(**{"/a": html("A", "Alpha", head)}))
    crawler, visits, _ = await run(site)
    assert crawler.status == "tdm_reserved"
    assert ROOT + "/b" not in [v.url for v in visits]  # the walk stops there


async def test_tdmrep_json_blocks_the_site_before_any_page() -> None:
    rules = json.dumps([{"location": "/*", "tdm-reservation": 1}])
    site = Site(three_page_site(**{"/.well-known/tdmrep.json": (200, {}, rules)}))
    crawler, visits, _ = await run(site)
    assert (crawler.status, visits) == ("tdm_reserved", [])
    assert "/" not in site.requested


async def test_tdmrep_json_without_reservation_allows_crawl() -> None:
    rules = json.dumps([{"location": "/*", "tdm-reservation": 0}])
    site = Site(three_page_site(**{"/.well-known/tdmrep.json": (200, {}, rules)}))
    assert (await run(site))[0].status == "ok"


@pytest.mark.parametrize(
    "page",
    [
        (200, {"content-type": "text/html", "x-robots-tag": "noai"}, html("B", "Beta")),
        html("B", "Beta", '<meta name="robots" content="noindex, follow">'),
    ],
)
async def test_noai_and_noindex_pages_are_blocked(page: Any) -> None:
    site = Site(three_page_site(**{"/b": page}))
    _, visits, _ = await run(site)
    [blocked] = [v for v in visits if v.url == ROOT + "/b"]
    assert (blocked.kind, blocked.reason, blocked.markdown) == ("blocked", "noai_or_noindex", "")


async def test_page_budget() -> None:
    crawler, visits, _ = await run(Site(three_page_site()), max_pages=2)
    assert len(pages(visits)) == 2
    assert not crawler.exhausted  # pages were left: missing ones are not "removed"


async def test_scope_rules_are_enforced() -> None:
    extra = {
        "/reports/one": html("One", "Report one"),
        "/reports/draft-two": html("Two", "Draft two"),
        "/about": html("About", "About us"),
    }
    home = html("Home", "Welcome").replace(
        "</main>",
        "<a href='/reports/one'>1</a><a href='/reports/draft-two'>2</a>"
        "<a href='/about'>A</a></main>",
    )
    site = Site({"/": home, **extra})
    scope = Scope(allow=("/", "/reports/*"), deny=("/reports/draft-*",))
    _, visits, _ = await run(site, scope=scope)
    assert pages(visits) == [ROOT + "/", ROOT + "/reports/one"]
    assert "/reports/draft-two" not in site.requested  # never fetched
    assert "/about" not in site.requested
    assert not Scope(allow=("/reports/*",)).admits(ROOT + "/about")
    assert Scope(deny=("/private/*",)).admits(ROOT + "/public")


async def test_special_category_pages_are_blocked_unless_whitelisted() -> None:
    extra = {"/health/patients": html("Patient stories", "Stories")}
    home = html("Home", "Welcome").replace(
        "</main>", "<a href='/health/patients'>P</a><a href='/a'>A</a></main>"
    )
    site = Site({"/": home, "/a": html("Grid outlook", "Grid"), **extra})

    def special(url: str, title: str) -> str | None:
        return None if whitelisted(url, ["/health/*"]) else special_category(url, title)

    _, visits, _ = await run(site, special=special_category)
    [blocked] = [v for v in visits if v.kind == "blocked"]
    assert (blocked.url, blocked.reason, blocked.special_category) == (
        ROOT + "/health/patients",
        "special_category",
        "health",
    )
    assert blocked.markdown == "" and blocked.raw == b""  # nothing kept
    _, visits, _ = await run(Site({"/": home, "/a": html("A", "Grid"), **extra}), special=special)
    assert ROOT + "/health/patients" in pages(visits)


@pytest.mark.parametrize(
    ("url", "title", "category"),
    [
        ("https://x.example/news/patient-outcomes", "", "health"),
        ("https://x.example/p/1", "Mental health services", "health"),
        ("https://x.example/faith/communities", "", "religion"),
        ("https://x.example/people/candidate-smith", "", "political_person"),
        ("https://x.example/about/lgbtq-network", "", "sexual_orientation"),
        ("https://x.example/union-membership", "", "trade_union"),
        ("https://x.example/a", "Criminal records of local officials", "criminal_record"),
        ("https://x.example/reports/offshore-wind-2026", "Offshore wind outlook", None),
        ("https://x.example/healthy-grid", "", None),  # whole words only
    ],
)
def test_special_category_patterns(url: str, title: str, category: str | None) -> None:
    assert special_category(url, title) == category


def test_explicit_publication_dates_only() -> None:
    meta = '<meta property="article:published_time" content="2026-03-01T09:00:00Z">'
    assert published_on(html("A", "x", meta).encode()) == date(2026, 3, 1)
    dc = '<meta name="DC.date.issued" content="2025/11/30">'
    assert published_on(html("A", "x", dc).encode()) == date(2025, 11, 30)
    ld = '<script type="application/ld+json">{"@graph": [{"datePublished": "2024-02-29"}]}</script>'
    assert published_on(html("A", "x", ld).encode()) == date(2024, 2, 29)
    # A date in the text, or a modification date, is not a publication date.
    text = html("A", "Published on 2026-03-01 and updated").encode()
    assert published_on(text) is None
    modified = '<meta property="article:modified_time" content="2026-03-01">'
    assert published_on(html("A", "x", modified).encode()) is None
    assert published_on(html("A", "x", '<meta name="date" content="soon">').encode()) is None


async def test_revisit_tells_gone_and_moved_pages_apart() -> None:
    site = Site(
        three_page_site(
            **{
                "/gone": (410, {}, "gone"),
                "/old": (301, {"location": "/a"}, ""),
            }
        )
    )
    async with site.client() as http:
        crawler = SiteCrawler(
            http,
            ROOT + "/",
            max_pages=5,
            scope=Scope(),
            special=no_special,
            limiter=Clock().limiter(),
        )
        await crawler.check()
        assert (await crawler.revisit(ROOT + "/b")).kind == "page"
        assert (await crawler.revisit(ROOT + "/nothing")).reason == "http_404"
        assert (await crawler.revisit(ROOT + "/gone")).reason == "http_410"
        moved = await crawler.revisit(ROOT + "/old")
        assert (moved.kind, moved.reason, moved.url) == ("missing", "moved", ROOT + "/old")


def test_normalise_strips_fragment_and_tracking_parameters() -> None:
    assert (
        normalise("https://Site.example/a?utm_source=x&id=3&fbclid=y#top")
        == "https://site.example/a?id=3"
    )
    assert normalise("https://site.example") == "https://site.example/"


def resolver(addresses: dict[str, list[str]]) -> Callable[[str], Any]:
    async def resolve(host: str) -> list[str]:
        if host not in addresses:
            raise OSError("unknown host")
        return addresses[host]

    return resolve


@pytest.mark.parametrize(
    ("url", "addresses", "code"),
    [
        ("https://site.example/", [PUBLIC], None),
        ("http://site.example:80/", [PUBLIC], None),
        ("https://site.example:8443/", [PUBLIC], "bad_port"),
        ("ftp://site.example/", [PUBLIC], "bad_url"),
        ("https://site.example/", ["127.0.0.1"], "not_public"),
        ("https://site.example/", ["10.1.2.3"], "not_public"),
        ("https://site.example/", ["172.20.0.5"], "not_public"),  # the Compose network
        ("https://site.example/", ["169.254.169.254"], "not_public"),
        ("https://site.example/", ["::1"], "not_public"),
        ("https://site.example/", [PUBLIC, "192.168.1.1"], "not_public"),
        ("https://nowhere.example/", [PUBLIC], "unresolvable"),
    ],
)
async def test_only_public_urls_are_fetched(
    url: str, addresses: list[str], code: str | None
) -> None:
    resolve = resolver({"site.example": addresses})
    if code is None:
        await require_public_url(url, resolve)
        return
    with pytest.raises(FetchError) as refused:
        await require_public_url(url, resolve)
    assert refused.value.code == code


async def test_a_redirect_to_an_internal_host_is_not_followed() -> None:
    site = Site({"/": (302, {"location": "http://ragflow/v1/datasets"}, "")})
    resolve = resolver({"site.example": [PUBLIC], "ragflow": ["172.20.0.7"]})
    async with site.client() as http:
        public_only(http, resolve)
        with pytest.raises(FetchError) as refused:
            await http.get(ROOT + "/")
    assert refused.value.code == "not_public"
    assert site.requested == ["/"]  # the internal request never went out


def test_cli_crawl_arguments() -> None:
    args = cli.build_parser().parse_args(
        [
            "crawl",
            ROOT,
            "--tag",
            "sample-web",
            "--max-pages",
            "5",
            "--licence",
            "terms ok",
            "--allow",
            "/reports/*",
            "--deny",
            "/reports/draft-*",
            "--schedule",
            "weekly",
        ]
    )
    assert (args.site_url, args.max_pages, args.tag) == (ROOT, 5, ["sample-web"])
    assert (args.allow, args.deny, args.schedule) == (
        ["/reports/*"],
        ["/reports/draft-*"],
        "weekly",
    )
    with pytest.raises(SystemExit):
        cli.main(["crawl", ROOT, "--tag", "sample-web", "--max-pages", "0", "--licence", "x"])
