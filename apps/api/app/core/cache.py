"""Tenant-scoped cache helpers. The only module that talks to Redis.

Every key is prefixed with the tenant ID, so a value written for one tenant can
never be read by another. Callers pass a tenant UUID and a logical key; they never
build Redis keys or hold a Redis client themselves. Direct Redis use elsewhere in
``app/`` is rejected by tests/test_logging_policy.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from typing import Protocol
from uuid import UUID

import redis.asyncio as redis

KEY_PREFIX = "t"
MAX_TTL_SECONDS = 30 * 24 * 3600  # never outlive the 30-day chat-history cap


class CacheClient(Protocol):
    def get(self, name: str) -> Awaitable[bytes | str | None]: ...

    def set(self, name: str, value: str, ex: int) -> Awaitable[object]: ...

    def scan_iter(self, match: str, count: int) -> AsyncIterator[bytes | str]: ...

    def delete(self, *names: str) -> Awaitable[object]: ...

    def aclose(self) -> Awaitable[None]: ...


_client: CacheClient | None = None


def tenant_key(tenant_id: UUID, key: str) -> str:
    """The Redis key for ``key`` in ``tenant_id``'s namespace: ``t:<tenant_id>:<key>``."""
    if not isinstance(tenant_id, UUID):
        raise TypeError("tenant_id must be a UUID")
    if not key:
        raise ValueError("cache key must not be empty")
    return f"{KEY_PREFIX}:{tenant_id}:{key}"


def configure(client: CacheClient | None) -> None:
    """Install the client used by get/set (tests pass a fake; None uninstalls)."""
    global _client
    _client = client


def connect(url: str) -> None:
    """Create the process-wide Redis client from a URL."""
    configure(redis.from_url(url, decode_responses=True))


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _require_client() -> CacheClient:
    if _client is None:
        raise RuntimeError("cache is not configured; call app.core.cache.connect() at startup")
    return _client


async def get(tenant_id: UUID, key: str) -> str | None:
    value = await _require_client().get(tenant_key(tenant_id, key))
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


async def set(tenant_id: UUID, key: str, value: str, ttl: int) -> None:
    """Store ``value`` for ``ttl`` seconds (required, 1 .. 30 days)."""
    if not 0 < ttl <= MAX_TTL_SECONDS:
        raise ValueError(f"ttl must be between 1 and {MAX_TTL_SECONDS} seconds")
    await _require_client().set(tenant_key(tenant_id, key), value, ex=ttl)


async def scan(tenant_id: UUID, prefix: str) -> AsyncIterator[tuple[str, str]]:
    """Every ``(key, value)`` in ``tenant_id``'s namespace whose key starts with ``prefix``
    (keys as callers name them, without the tenant prefix). For maintenance, such as the
    withdrawal purge (P1b-03); never on a request path."""
    if not prefix or any(c in prefix for c in "*?[]\\"):
        raise ValueError("prefix must be a non-empty literal")
    client = _require_client()
    namespace = tenant_key(tenant_id, prefix)
    start = len(namespace) - len(prefix)
    async for name in client.scan_iter(match=namespace + "*", count=500):
        name = name.decode("utf-8") if isinstance(name, bytes) else name
        value = await get(tenant_id, name[start:])
        if value is not None:
            yield name[start:], value


async def delete(tenant_id: UUID, key: str) -> None:
    await _require_client().delete(tenant_key(tenant_id, key))


async def clear_tenant(tenant_id: UUID) -> int:
    """Delete every key in ``tenant_id``'s namespace; how many went. For the termination
    purge and the switch to "no history" (P1b-14): rare administrative actions, never on
    a chat request path."""
    client = _require_client()
    namespace = tenant_key(tenant_id, "x")[:-1]
    names = [
        name.decode("utf-8") if isinstance(name, bytes) else name
        async for name in client.scan_iter(match=namespace + "*", count=500)
    ]
    for start in range(0, len(names), 500):
        await client.delete(*names[start : start + 500])
    return len(names)
