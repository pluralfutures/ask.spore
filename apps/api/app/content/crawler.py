"""The crawler (P0-10, P1b-04): one site within its scope, politely.

Before fetching any page it reads the site's robots.txt (RFC 9309) and
``/.well-known/tdmrep.json`` (TDMRep): that is the site's allow decision. It then walks
same-host links breadth first, within the site's scope rules (path allow and deny
patterns), honouring robots rules, and renders each HTML page to readable Markdown.
The EU text-and-data-mining rights reservation blocks the whole site: a reserving
``tdmrep.json``, or a ``tdm-reservation: 1`` header or meta tag on any page, ends the
crawl. Pages marked ``noai`` or ``noindex`` (meta robots or ``X-Robots-Tag``), pages
without readable content and special-category pages (``app.content.special``, unless
whitelisted) are reported as blocked, never returned for ingestion.

Every request, robots.txt included, waits its turn at a per-host rate limit
(``HostLimiter``): one request per host per second, or the site's ``Crawl-delay``
(capped at 30 seconds) when it asks for more. Publication dates come from explicit
page metadata only (``published_on``), never guessed from the text.

Crawled text is untrusted input; the chat orchestrator wraps it as such.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter, deque
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date
from fnmatch import fnmatchcase
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
# Fetches per crawl, at most this many times the page budget (blocked pages count too).
FETCHES_PER_PAGE = 3
TRACKING_PARAMS = re.compile(r"^(utm_.*|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|_ga|_hs.*)$")
# Not HTML pages; not fetched by the crawler (propose such files in the console).
SKIP_SUFFIXES = frozenset(
    ".pdf .doc .docx .ppt .pptx .xls .xlsx .zip .gz .jpg .jpeg .png .gif .svg .webp "
    ".mp3 .mp4 .avi .mov .css .js .json .xml .rss .ico".split()
)
_ROBOTS_META = re.compile(
    rb"""<meta\s[^>]*name\s*=\s*["']?(?:robots|ask\.spore-crawler)["']?[^>]*>""", re.IGNORECASE
)
_CONTENT = re.compile(rb"""content\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_EXCLUDING = frozenset({"noai", "noindex", "none"})
# Explicit publication-date metadata, by meta name/property/itemprop (lower case).
_DATE_META = frozenset(
    {
        "article:published_time",
        "og:published_time",
        "datepublished",
        "date",
        "dc.date",
        "dc.date.issued",
        "dcterms.date",
        "dcterms.issued",
        "citation_publication_date",
        "citation_date",
        "publication_date",
        "pubdate",
    }
)
_ISO_DATE = re.compile(r"^\s*(\d{4})[-/](\d{2})[-/](\d{2})")
GONE_STATUSES = frozenset({404, 410})

CrawlStatus = Literal["ok", "robots_disallowed", "tdm_reserved", "unreachable"]
VisitKind = Literal["page", "blocked", "missing", "error"]


class HostLimiter:
    """At most one request per host per interval, across every crawl of the worker."""

    def __init__(
        self,
        interval: float = DEFAULT_DELAY_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._next: dict[str, float] = {}

    async def wait(self, host: str, interval: float | None = None) -> None:
        now = self._clock()
        ready = self._next.get(host, now)
        if ready > now:
            await self._sleep(ready - now)
            now = ready
        self._next[host] = now + max(interval or 0.0, self.interval)


@dataclass(frozen=True)
class Scope:
    """A site's scope rules: shell-style patterns on the URL path (``/reports/*``). A page
    is in scope when it matches an allow pattern (or there are none) and no deny one."""

    allow: Sequence[str] = ()
    deny: Sequence[str] = ()

    def admits(self, url: str) -> bool:
        path = urlsplit(url).path or "/"
        if self.allow and not any(fnmatchcase(path, p) for p in self.allow):
            return False
        return not any(fnmatchcase(path, p) for p in self.deny)


@dataclass(frozen=True)
class Visit:
    """What the crawler found at one URL.

    - ``page``: readable HTML in scope (``title``, ``markdown``, ``raw`` HTML, and the
      explicit ``published_on`` if any);
    - ``blocked``: fetched but not to be ingested (``reason``: ``noai_or_noindex``,
      ``no_content``, ``special_category`` with ``special_category``, ``robots``,
      ``out_of_scope``, ``off_site``, ``not_html``);
    - ``missing``: gone (HTTP 404 or 410, or moved to another URL: ``reason``);
    - ``error``: could not be fetched this time (``reason`` is the fetch error code).
    """

    url: str
    kind: VisitKind
    reason: str | None = None
    special_category: str | None = None
    title: str = ""
    markdown: str = ""
    raw: bytes = b""
    published_on: date | None = None


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


class _DateMeta(HTMLParser):
    """Publication-date candidates from ``<meta>`` tags and JSON-LD ``datePublished``."""

    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []
        self._in_json_ld = False
        self._json: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k.lower(): v or "" for k, v in attrs}
        if tag == "meta":
            key = values.get("property") or values.get("name") or values.get("itemprop") or ""
            if key.lower() in _DATE_META and values.get("content"):
                self.values.append(values["content"])
        if tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._in_json_ld = True

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            self.values.extend(_json_ld_dates("".join(self._json)))
            self._json = []


def _json_ld_dates(raw: str) -> list[str]:
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    found: list[str] = []
    stack = [data]
    while stack and len(found) < 10:
        item = stack.pop()
        if isinstance(item, dict):
            value = item.get("datePublished")
            if isinstance(value, str):
                found.append(value)
            stack.extend(v for v in item.values() if isinstance(v, dict | list))
        elif isinstance(item, list):
            stack.extend(item)
    return found


def published_on(html: bytes) -> date | None:
    """The page's publication date from explicit metadata only, or None."""
    parser = _DateMeta()
    try:
        parser.feed(html[:262144].decode("utf-8", errors="replace"))
    except Exception:  # malformed markup: no date rather than a guess
        return None
    for value in parser.values:
        match = _ISO_DATE.match(value)
        if match:
            try:
                return date(int(match[1]), int(match[2]), int(match[3]))
            except ValueError:
                continue
    return None


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


class SiteCrawler:
    """One crawl of one site: ``check`` the allow decision, then ``walk`` the pages, then
    ``revisit`` pages known from earlier crawls that the walk did not reach."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        start_url: str,
        *,
        max_pages: int,
        scope: Scope,
        special: Callable[[str, str], str | None],
        limiter: HostLimiter,
    ) -> None:
        require_http_url(start_url)
        self.http = http
        self.start = normalise(start_url)
        parts = urlsplit(self.start)
        self.host = parts.hostname or ""
        self.root = f"{parts.scheme}://{parts.netloc}"
        self.max_pages = max_pages
        self.scope = scope
        self.special = special
        self.limiter = limiter
        self.status: CrawlStatus = "ok"
        self.exhausted = False  # the walk reached every in-scope page it found
        self.skipped: Counter[str] = Counter()
        self.delay = DEFAULT_DELAY_SECONDS
        self._robots: RobotFileParser | None = None

    async def _get(self, url: str) -> httpx.Response:
        await self.limiter.wait(self.host, self.delay)
        return await self.http.get(url)

    async def check(self) -> CrawlStatus:
        """The site's allow decision from robots.txt and the TDM reservation.

        RFC 9309 §2.3.1: a 4xx answer for robots.txt means no rules (crawl allowed); a
        5xx answer or an unreachable server means assume complete disallow, so no crawl.
        """
        try:
            response = await self._get(self.root + "/robots.txt")
        except (httpx.HTTPError, FetchError):
            self.status = "unreachable"
            return self.status
        if response.status_code >= 500:
            self.status = "unreachable"
            return self.status
        robots = RobotFileParser()
        robots.parse(response.text.splitlines() if response.status_code == 200 else [])
        self._robots = robots
        declared = robots.crawl_delay(USER_AGENT)
        if declared:
            self.delay = min(max(float(declared), DEFAULT_DELAY_SECONDS), MAX_DELAY_SECONDS)
        if not robots.can_fetch(USER_AGENT, self.start):
            self.status = "robots_disallowed"
        elif await self._site_reserves_tdm():
            self.status = "tdm_reserved"
        return self.status

    async def _site_reserves_tdm(self) -> bool:
        """TDMRep ``/.well-known/tdmrep.json``: any rule with ``tdm-reservation: 1``.

        Conservative: a reservation for any path blocks the whole site.
        """
        try:
            response = await self._get(self.root + "/.well-known/tdmrep.json")
        except (httpx.HTTPError, FetchError):
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

    def _allowed(self, url: str) -> bool:
        return self._robots is not None and self._robots.can_fetch(USER_AGENT, url)

    async def visit(self, url: str, *, links: list[str] | None = None) -> Visit:
        """Fetch one URL and judge it; with ``links``, collect the page's links into it."""
        if not self._allowed(url):
            return Visit(url, "blocked", "robots")
        if not self.scope.admits(url):
            return Visit(url, "blocked", "out_of_scope")
        try:
            await self.limiter.wait(self.host, self.delay)
            page = await fetch(self.http, url)
        except FetchError as exc:
            if exc.status in GONE_STATUSES:
                return Visit(url, "missing", f"http_{exc.status}")
            return Visit(url, "error", exc.code)
        final = normalise(page.url)
        if not _same_site(final, self.host):
            return Visit(url, "blocked", "off_site")
        if tdm_reserved(page.headers, page.content, page.is_html):
            self.status = "tdm_reserved"
            return Visit(final, "blocked", "tdm_reserved")
        if not page.is_html:
            return Visit(final, "blocked", "not_html")
        if links is not None:
            parser = _Links()
            parser.feed(page.content.decode("utf-8", errors="replace"))
            if not parser.nofollow:
                links.extend(normalise(urljoin(final, href)) for href in parser.hrefs)
        if _excluded_by_robots_directives(page.headers, page.content):
            return Visit(final, "blocked", "noai_or_noindex")
        rendered = render(page.content, final)
        if rendered is None:
            return Visit(final, "blocked", "no_content")
        title, markdown = rendered
        category = self.special(final, title)
        if category is not None:
            return Visit(final, "blocked", "special_category", special_category=category)
        return Visit(
            final,
            "page",
            title=title,
            markdown=markdown,
            raw=page.content,
            published_on=published_on(page.content),
        )

    async def walk(self) -> AsyncIterator[Visit]:
        """Breadth first from the start URL, up to ``max_pages`` pages; call ``check``
        first. Stops at once when a page reserves TDM rights (``status``)."""
        if self.status != "ok" or self._robots is None:
            return
        queue: deque[str] = deque([self.start])
        seen = {self.start}
        pages = fetches = 0
        while queue:
            if pages >= self.max_pages or fetches >= FETCHES_PER_PAGE * self.max_pages:
                return
            url = queue.popleft()
            if not self._allowed(url):
                self.skipped["robots"] += 1
                continue
            links: list[str] = []
            fetches += 1
            found = await self.visit(url, links=links)
            if found.reason == "tdm_reserved":  # the whole site reserves its rights
                yield found
                return
            for target in links:
                suffix = Path(urlsplit(target).path).suffix.lower()
                if (
                    target not in seen
                    and _same_site(target, self.host)
                    and suffix not in SKIP_SUFFIXES
                    and self.scope.admits(target)
                ):
                    seen.add(target)
                    queue.append(target)
            if found.kind == "page":
                if found.url != url and found.url in seen:
                    continue  # a redirect to a page the walk already has
                seen.add(found.url)
                pages += 1
            elif found.kind != "blocked" or found.reason in ("off_site", "not_html"):
                self.skipped[found.reason or found.kind] += 1
                continue
            yield found
        self.exhausted = True

    async def revisit(self, url: str) -> Visit:
        """A page known from an earlier crawl that the walk did not reach: is it still
        there? A redirect elsewhere counts as moved (``missing``)."""
        found = await self.visit(url)
        if found.kind in ("page", "blocked") and found.url != url and found.reason != "robots":
            return Visit(url, "missing", "moved")
        return found
