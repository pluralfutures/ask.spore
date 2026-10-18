"""Client-side throttle for LLM calls: requests per second and tokens per minute.

Keeps one process under the provider's limits (Scaleway counts requests and input
plus output tokens per minute per organisation). A call reserves its estimated
tokens before it is sent and settles the difference once usage is known, so a
long answer delays the calls after it rather than overshooting the window.
Limits are per process: the API and the eval harness each hold their own.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

CHARS_PER_TOKEN = 4  # same estimate as the orchestrator's context budget


def estimate_tokens(texts: list[str], max_output_tokens: int) -> int:
    """Input estimate from character count, plus the output the call may produce."""
    return sum(len(t) for t in texts) // CHARS_PER_TOKEN + max_output_tokens


class TokenBucket:
    def __init__(
        self,
        requests_per_second: float,
        tokens_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = 1.0 / requests_per_second
        self._capacity = float(tokens_per_minute)
        self._refill_per_second = tokens_per_minute / 60.0
        self._clock = clock
        self._sleep = sleep
        self._tokens = self._capacity
        self._updated = clock()
        self._next_request = self._updated
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(
            self._capacity, self._tokens + (now - self._updated) * self._refill_per_second
        )
        self._updated = now

    async def acquire(self, tokens: int) -> int:
        """Wait for a request slot and ``tokens`` of capacity; returns what was reserved."""
        tokens = min(tokens, int(self._capacity))  # one oversized call must still pass
        async with self._lock:
            while True:
                self._refill()
                now = self._clock()
                wait = max(
                    self._next_request - now,
                    (tokens - self._tokens) / self._refill_per_second,
                )
                if wait <= 0:
                    break
                await self._sleep(wait)
            self._tokens -= tokens
            self._next_request = self._clock() + self._interval
        return tokens

    def settle(self, reserved: int, used: int) -> None:
        """Correct a reservation once the call's real usage is known (may go negative)."""
        self._refill()
        self._tokens = min(self._capacity, self._tokens + reserved - used)
