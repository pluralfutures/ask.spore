"""Fetching public web content for ingestion (P0-09) and crawling (P0-10).

Identifies itself with a descriptive user agent (architecture §6.4), refuses
anything but http(s), caps response size, and detects the EU text-and-data-mining
rights reservation (DSM Directive Art. 4, TDMRep): the ``tdm-reservation: 1``
response header or the equivalent ``<meta name="tdm-reservation">`` tag. Reserved
content is never ingested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

USER_AGENT = "ask.spore-crawler/0.1 (research corpus; +https://pluralfutures.com)"
MAX_BYTES = 100 * 1024 * 1024
TIMEOUT_SECONDS = 30.0
MAX_REDIRECTS = 5

_TDM_META = re.compile(
    rb"""<meta\s[^>]*name\s*=\s*["']?tdm-reservation["']?[^>]*>""", re.IGNORECASE
)
_CONTENT_ONE = re.compile(rb"""content\s*=\s*["']?\s*1\b""", re.IGNORECASE)


class FetchError(RuntimeError):
    """The URL could not be fetched, or must not be used."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Fetched:
    url: str  # after redirects
    status: int
    content_type: str  # media type only, lower-case, e.g. "text/html"
    headers: httpx.Headers
    content: bytes

    @property
    def is_html(self) -> bool:
        return self.content_type in {"text/html", "application/xhtml+xml"}


def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
    )


def require_http_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise FetchError("bad_url", f"not an http(s) URL: {url}")


def tdm_reserved(headers: httpx.Headers, content: bytes = b"", is_html: bool = False) -> bool:
    """True if the response reserves text-and-data-mining rights (TDMRep)."""
    if headers.get("tdm-reservation", "").strip() == "1":
        return True
    if is_html:
        for tag in _TDM_META.findall(content[:65536]):
            if _CONTENT_ONE.search(tag):
                return True
    return False


async def fetch(http: httpx.AsyncClient, url: str) -> Fetched:
    """GET ``url``; raise FetchError on failure, non-200 or an oversized body."""
    require_http_url(url)
    try:
        async with http.stream("GET", url) as response:
            if response.status_code != 200:
                raise FetchError("http_status", f"HTTP {response.status_code} for {url}")
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_BYTES:
                raise FetchError("too_large", f"larger than {MAX_BYTES} bytes: {url}")
            body = bytearray()
            async for part in response.aiter_bytes():
                body += part
                if len(body) > MAX_BYTES:
                    raise FetchError("too_large", f"larger than {MAX_BYTES} bytes: {url}")
            media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            return Fetched(
                url=str(response.url),
                status=response.status_code,
                content_type=media_type,
                headers=response.headers,
                content=bytes(body),
            )
    except httpx.TimeoutException:
        raise FetchError("timeout", f"timed out fetching {url}") from None
    except httpx.TooManyRedirects:
        raise FetchError("redirects", f"too many redirects: {url}") from None
    except httpx.TransportError:
        raise FetchError("unreachable", f"could not reach {url}") from None
