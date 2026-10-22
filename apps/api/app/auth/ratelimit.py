"""Per-client-IP limits on the unauthenticated sign-in routes (P1b-08).

``POST /auth/link`` (and tenant discovery and SSO start) are public: without a limit
per client, one host could make us send many links or probe many domains. The
per-user limit of P1a-02 (``links_per_window``) does not cover an attacker spreading
requests over many addresses. Here each route allows ``limit`` requests per client IP
in a sliding window; the next is answered 429 before anything else happens: no lookup,
no cookie, no email.

The client IP is the last ``X-Forwarded-For`` entry when the request came through
Caddy (which sets it to the connecting address and does not trust an incoming one),
else the socket's peer. Only its SHA-256 is held, in memory, for the window; it is
never logged. Limits are per API process (the Instance runs one).
"""

from __future__ import annotations

import hashlib
import time
from collections import deque
from collections.abc import Callable
from typing import Final

from starlette.requests import Request

MAX_TRACKED: Final = 50_000  # clients held at once; the oldest are dropped first


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class IpRateLimiter:
    """A sliding-window counter per client, keyed by the SHA-256 of its address."""

    def __init__(
        self, limit: int, window_seconds: float, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, address: str) -> bool:
        """Count one request from ``address``; False when it is over the limit."""
        now = self._clock()
        key = hashlib.sha256(address.encode("utf-8")).hexdigest()
        hits = self._hits.pop(key, None) or deque()
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        allowed = len(hits) < self._limit
        if allowed:
            hits.append(now)
        self._hits[key] = hits  # re-inserted last: dicts keep insertion order
        while len(self._hits) > MAX_TRACKED:
            del self._hits[next(iter(self._hits))]
        return allowed

    def retry_after(self, address: str) -> int:
        key = hashlib.sha256(address.encode("utf-8")).hexdigest()
        hits = self._hits.get(key)
        if not hits:
            return 0
        return max(1, int(hits[0] + self._window - self._clock()) + 1)
