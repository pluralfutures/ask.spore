import fnmatch
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest

from app.core import cache

TENANT_A = UUID("00000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("00000000-0000-4000-8000-00000000000b")


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, name: str) -> str | None:
        return self.store.get(name)

    async def set(self, name: str, value: str, ex: int) -> bool:
        self.store[name] = value
        self.ttls[name] = ex
        return True

    async def scan_iter(self, match: str, count: int) -> AsyncIterator[str]:
        for name in list(self.store):
            if fnmatch.fnmatchcase(name, match):
                yield name

    async def delete(self, *names: str) -> int:
        removed = [n for n in names if self.store.pop(n, None) is not None]
        return len(removed)

    async def aclose(self) -> None:
        pass


@pytest.fixture
async def fake() -> AsyncIterator[FakeRedis]:
    client = FakeRedis()
    cache.configure(client)
    yield client
    cache.configure(None)


def test_key_carries_tenant_prefix() -> None:
    assert cache.tenant_key(TENANT_A, "answer:abc") == f"t:{TENANT_A}:answer:abc"


async def test_set_writes_tenant_prefixed_key(fake: FakeRedis) -> None:
    await cache.set(TENANT_A, "answer:abc", "cached", ttl=60)
    assert list(fake.store) == [f"t:{TENANT_A}:answer:abc"]
    assert fake.ttls[f"t:{TENANT_A}:answer:abc"] == 60
    assert await cache.get(TENANT_A, "answer:abc") == "cached"


async def test_other_tenant_cannot_read_value(fake: FakeRedis) -> None:
    await cache.set(TENANT_A, "answer:abc", "tenant A answer", ttl=60)
    assert await cache.get(TENANT_B, "answer:abc") is None


async def test_same_logical_key_is_separate_per_tenant(fake: FakeRedis) -> None:
    await cache.set(TENANT_A, "k", "a", ttl=60)
    await cache.set(TENANT_B, "k", "b", ttl=60)
    assert await cache.get(TENANT_A, "k") == "a"
    assert await cache.get(TENANT_B, "k") == "b"


async def test_tenant_id_must_be_uuid(fake: FakeRedis) -> None:
    with pytest.raises(TypeError):
        await cache.get("internal", "k")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        await cache.set(str(TENANT_A), "k", "v", ttl=60)  # type: ignore[arg-type]


async def test_empty_key_rejected(fake: FakeRedis) -> None:
    with pytest.raises(ValueError, match="empty"):
        await cache.get(uuid4(), "")


@pytest.mark.parametrize("ttl", [0, -1, cache.MAX_TTL_SECONDS + 1])
async def test_ttl_is_bounded(fake: FakeRedis, ttl: int) -> None:
    with pytest.raises(ValueError, match="ttl"):
        await cache.set(TENANT_A, "k", "v", ttl=ttl)


async def test_unconfigured_cache_fails_loudly() -> None:
    cache.configure(None)
    with pytest.raises(RuntimeError, match="not configured"):
        await cache.get(TENANT_A, "k")


async def test_bytes_values_are_decoded(fake: FakeRedis) -> None:
    fake.store[f"t:{TENANT_A}:k"] = b"raw"  # type: ignore[assignment]
    assert await cache.get(TENANT_A, "k") == "raw"
