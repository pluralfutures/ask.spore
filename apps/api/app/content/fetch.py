"""Fetching public web content for ingestion (P0-09) and crawling (P0-10).

Identifies itself with a descriptive user agent (architecture §6.4), refuses
anything but http(s), caps response size, and detects the EU text-and-data-mining
rights reservation (DSM Directive Art. 4, TDMRep): the ``tdm-reservation: 1``
response header or the equivalent ``<meta name="tdm-reservation">`` tag. Reserved
content is never ingested.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
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

    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        self.code = code
        self.status = status  # the HTTP status, for ``http_status``
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


def require_http_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise FetchError("bad_url", f"not an http(s) URL: {url}")


Resolver = Callable[[str], Awaitable[list[str]]]
# Opens the connection for one pinned request; tests pass an httpx.MockTransport.
Connector = Callable[[], httpx.AsyncBaseTransport]
PUBLIC_PORTS = frozenset({None, 80, 443})
# Cloud instance metadata services (AWS/GCP/Azure, Scaleway, AWS over IPv6, Alibaba). All
# are already non-global; named so a change to ``ipaddress`` cannot let one through.
METADATA_ADDRESSES = frozenset(
    ipaddress.ip_address(address)
    for address in ("169.254.169.254", "169.254.42.42", "fd00:ec2::254", "100.100.100.200")
)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


async def resolve_host(host: str) -> list[str]:
    """The IP addresses ``host`` resolves to."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def is_public_address(address: str) -> bool:
    """True for a global unicast address that is not a metadata service. IPv4-mapped and
    NAT64 IPv6 addresses are judged by the IPv4 address they carry."""
    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(
            address.split("%")[0]
        )
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast and ip not in METADATA_ADDRESSES


def _public_target(url: str) -> str:
    """The host of an http(s) URL on a default port; FetchError ``bad_url`` or
    ``bad_port`` otherwise."""
    require_http_url(url)
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        raise FetchError("bad_url", "not a valid port") from None
    if port not in PUBLIC_PORTS:
        raise FetchError("bad_port", "only the default http(s) ports are crawled")
    return parts.hostname or ""


async def public_addresses(host: str, resolve: Resolver = resolve_host) -> list[str]:
    """Resolve ``host`` once; every address it resolves to must be public (FetchError
    ``unresolvable`` or ``not_public`` otherwise)."""
    try:
        addresses = await resolve(host)
    except (OSError, UnicodeError):
        raise FetchError("unresolvable", "the host does not resolve") from None
    if not addresses:
        raise FetchError("unresolvable", "the host does not resolve")
    if not all(is_public_address(address) for address in addresses):
        raise FetchError("not_public", "the host is not on the public internet")
    return addresses


async def require_public_url(url: str, resolve: Resolver = resolve_host) -> None:
    """Refuse a URL the API or the worker must not fetch for a content editor: anything
    but http(s) on the default ports, or a host that resolves to a private, loopback,
    link-local, multicast, metadata or otherwise non-global address (the Compose
    network, RAGFlow, the database). FetchError codes: ``bad_url``, ``bad_port``,
    ``unresolvable``, ``not_public``. Checked at registration and before each crawl;
    the connection itself is guarded by ``PinnedTransport``."""
    await public_addresses(_public_target(url), resolve)


class PinnedTransport(httpx.AsyncBaseTransport):
    """Connects only to an address it has just checked (P1b-18, decision 9).

    For every request, so for every redirect hop the client follows, the URL is checked
    as in ``require_public_url``, the host is resolved once, and the connection goes to
    the first resolved address: the request is re-addressed to that IP, keeping the Host
    header and, for https, the hostname for SNI and certificate verification. Nothing
    resolves the name a second time, so a DNS answer that changes between the check and
    the connection (DNS rebinding) cannot reach an internal address. Connections are
    pooled per hostname, so one host's request never rides another host's TLS session.
    A refused request raises FetchError before anything is sent."""

    def __init__(self, resolve: Resolver = resolve_host, connect: Connector | None = None):
        self._resolve = resolve
        self._connect: Connector = connect or httpx.AsyncHTTPTransport
        self._pools: dict[str, httpx.AsyncBaseTransport] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = _public_target(str(request.url))
        address = (await public_addresses(host, self._resolve))[0]
        extensions = dict(request.extensions)
        if request.url.scheme == "https" and not _is_ip_literal(host):
            extensions["sni_hostname"] = host
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=address.split("%")[0]),
            headers=request.headers,  # carries the original Host header
            stream=request.stream,
            extensions=extensions,
        )
        pool = self._pools.get(host)
        if pool is None:
            pool = self._pools[host] = self._connect()
        return await pool.handle_async_request(pinned)

    async def aclose(self) -> None:
        pools, self._pools = list(self._pools.values()), {}
        for pool in pools:
            await pool.aclose()


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def http_client(
    resolve: Resolver = resolve_host, connect: Connector | None = None
) -> httpx.AsyncClient:
    """The client for every server-side fetch of an editor-supplied, manifest or crawled
    URL: public addresses only, pinned per request (``PinnedTransport``), at most
    ``MAX_REDIRECTS`` redirects, each re-checked. Proxy settings from the environment
    are ignored, as a proxy would resolve the name itself."""
    return httpx.AsyncClient(
        transport=PinnedTransport(resolve, connect),
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        trust_env=False,
    )


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
                raise FetchError(
                    "http_status", f"HTTP {response.status_code} for {url}", response.status_code
                )
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
