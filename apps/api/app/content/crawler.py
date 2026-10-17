"""Minimal crawler (P0-10): one site, a page budget, no scheduling or change detection.

Before fetching any page it reads the site's robots.txt (RFC 9309) and
``/.well-known/tdmrep.json`` (TDMRep). It then walks same-host links breadth
first, honouring robots rules and crawl delay, and renders each HTML page to
readable Markdown. The EU text-and-data-mining rights reservation blocks the whole
site: a reserving ``tdmrep.json``, or a ``tdm-reservation: 1`` header or meta tag
on any page, ends the crawl and nothing from the site is returned for ingestion.
Pages marked ``noai`` or ``noindex`` (meta robots or ``X-Robots-Tag``) are skipped.

Crawled text is untrusted input; the chat orchestrator wraps it as such.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

from app.content.fetch import USER_AGENT, FetchError, fetch, require_http_url, tdm_reserved

DEFAULT_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 30.0
TRACKING_PARAMS = re.compile(r"^(utm_.*|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|_ga|_hs.*)$")
# Not HTML pages; not fetched by the crawler (ingest such files with `ask-spore ingest`).
SKIP_SUFFIXES = frozenset(
    ".pdf .doc .docx .ppt .pptx .xls .xlsx .zip .gz .jpg .jpeg .png .gif .svg .webp "
    ".mp3 .mp4 .avi .mov .css .js .json .xml .rss .ico".split()
)
_ROBOTS_META = re.compile(
    rb"""<meta\s[^>]*name\s*=\s*["']?(?:robots|ask\.spore-crawler)["']?[^>]*>""", re.IGNORECASE
)
_CONTENT = re.compile(rb"""content\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_EXCLUDING = frozenset({"noai", "noindex", "none"})

CrawlStatus = Literal["ok", "robots_disallowed", "tdm_reserved", "unreachable"]


@dataclass(frozen=True)
class Page:
    url: str  # canonical link: the page URL after redirects, tracking parameters removed
    title: str
    markdown: str


@dataclass
class CrawlReport:
    status: CrawlStatus
    pages: list[Page] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.nofollow = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("href") and "nofollow" not in (values.get("rel") or ""):
            self.hrefs.append(str(values["href"]))
        if tag == "meta" and (values.get("name") or "").lower() == "robots":
            if "nofollow" in (values.get("content") or "").lower():
                self.nofollow = True


def normalise(url: str) -> str:
    """Drop the fragment and tracking parameters; keep everything else."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    kept = urlencode([(k, v) for k, v in query if not TRACKING_PARAMS.match(k.lower())])
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", kept, ""))


def _same_site(url: str, host: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in {"http", "https"} and (parts.hostname or "") == host


def _excluded_by_robots_directives(headers: httpx.Headers, content: bytes) -> bool:
    directives = {d.strip().lower() for d in headers.get("x-robots-tag", "").split(",")}
    for tag in _ROBOTS_META.findall(content[:65536]):
        match = _CONTENT.search(tag)
        if match:
            directives |= {d.strip().lower() for d in match.group(1).decode().split(",")}
    return bool(directives & _EXCLUDING)


async def _robots(http: httpx.AsyncClient, root: str) -> RobotFileParser | None:
    """Parsed robots.txt; ``None`` means the site must not be crawled at all.

    RFC 9309 §2.3.1: a 4xx answer means no rules (crawl allowed); a 5xx answer or
    an unreachable server means assume complete disallow.
    """
    parser = RobotFileParser()
    try:
        response = await http.get(root + "/robots.txt")
    except httpx.HTTPError:
        return None
    if response.status_code >= 500:
        return None
    lines = response.text.splitlines() if response.status_code == 200 else []
    parser.parse(lines)
    return parser


async def _site_reserves_tdm(http: httpx.AsyncClient, root: str) -> bool:
    """TDMRep ``/.well-known/tdmrep.json``: any rule with ``tdm-reservation: 1``.

    Conservative: a reservation for any path blocks the whole site in Phase 0.
    """
    try:
        response = await http.get(root + "/.well-known/tdmrep.json")
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        rules = json.loads(response.content)
    except ValueError:
        return False
    return isinstance(rules, list) and any(
        isinstance(rule, dict) and str(rule.get("tdm-reservation")) == "1" for rule in rules
    )


def render(html: bytes, url: str) -> tuple[str, str] | None:
    """(title, markdown) of a page's readable content, or None if it has none."""
    text = html.decode("utf-8", errors="replace")
    markdown = trafilatura.extract(
        text,
        url=url,
        output_format="markdown",
        include_links=False,
        include_images=False,
        include_tables=True,
        favor_precision=True,
    )
    if not markdown or not markdown.strip():
        return None
    metadata = trafilatura.extract_metadata(text, default_url=url)
    title = (metadata.title if metadata and metadata.title else "") or urlsplit(url).path
    return title.strip(), markdown.strip()


async def crawl(
    http: httpx.AsyncClient,
    site_url: str,
    max_pages: int,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> CrawlReport:
    """Crawl ``site_url``'s host for up to ``max_pages`` readable HTML pages."""
    require_http_url(site_url)
    start = normalise(site_url)
    parts = urlsplit(start)
    host = parts.hostname or ""
    root = f"{parts.scheme}://{parts.netloc}"

    robots = await _robots(http, root)
    if robots is None:
        return CrawlReport("unreachable")
    if not robots.can_fetch(USER_AGENT, start):
        return CrawlReport("robots_disallowed")
    if await _site_reserves_tdm(http, root):
        return CrawlReport("tdm_reserved")
    declared = robots.crawl_delay(USER_AGENT)
    delay = min(float(declared), MAX_DELAY_SECONDS) if declared else DEFAULT_DELAY_SECONDS

    report = CrawlReport("ok")
    queue: deque[str] = deque([start])
    seen = {start}
    first = True
    while queue and len(report.pages) < max_pages:
        url = queue.popleft()
        if not robots.can_fetch(USER_AGENT, url):
            report.skipped["robots"] += 1
            continue
        if not first:
            await sleep(delay)
        first = False
        try:
            page = await fetch(http, url)
        except FetchError as exc:
            report.skipped[exc.code] += 1
            continue
        final = normalise(page.url)
        if not _same_site(final, host):
            report.skipped["off_site"] += 1
            continue
        if tdm_reserved(page.headers, page.content, page.is_html):
            return CrawlReport("tdm_reserved", skipped=report.skipped)
        if not page.is_html:
            report.skipped["not_html"] += 1
            continue

        links = _Links()
        links.feed(page.content.decode("utf-8", errors="replace"))
        if not links.nofollow:
            for href in links.hrefs:
                target = normalise(urljoin(final, href))
                suffix = Path(urlsplit(target).path).suffix.lower()
                if target not in seen and _same_site(target, host) and suffix not in SKIP_SUFFIXES:
                    seen.add(target)
                    queue.append(target)

        if _excluded_by_robots_directives(page.headers, page.content):
            report.skipped["noai_or_noindex"] += 1
            continue
        rendered = render(page.content, final)
        if rendered is None:
            report.skipped["no_content"] += 1
            continue
        title, markdown = rendered
        if final in {p.url for p in report.pages}:
            continue
        report.pages.append(Page(url=final, title=title, markdown=markdown))
    return report


def page_file_name(page: Page, index: int) -> str:
    path = urlsplit(page.url).path.strip("/") or "index"
    slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")[:80] or "index"
    return f"{index:03d}-{slug}.md"


def page_markdown(page: Page) -> str:
    """The Markdown file for one page (its canonical link, the URL, goes on the source row)."""
    return page.markdown + "\n"


def write_pages(pages: list[Page], out_dir: Path) -> list[Path]:
    """Write one Markdown file per page; return their paths in page order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, page in enumerate(pages, start=1):
        path = out_dir / page_file_name(page, index)
        path.write_text(page_markdown(page), encoding="utf-8")
        paths.append(path)
    return paths
