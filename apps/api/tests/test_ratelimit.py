"""Client-side LLM throttle (app.llm.ratelimit), with a fake clock."""

from __future__ import annotations

import asyncio

from app.llm.ratelimit import TokenBucket, estimate_tokens


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


def bucket(rps: float, tpm: int, clock: Clock) -> TokenBucket:
    return TokenBucket(rps, tpm, clock=clock, sleep=clock.sleep)


def test_estimate_counts_input_characters_and_output_budget() -> None:
    assert estimate_tokens(["a" * 400, "b" * 40], 100) == 210


async def test_requests_are_spaced_by_the_rate() -> None:
    clock = Clock()
    b = bucket(2, 1_000_000, clock)
    for _ in range(3):
        await b.acquire(10)
    assert clock.sleeps == [0.5, 0.5]


async def test_tokens_per_minute_hold_back_the_next_call() -> None:
    clock = Clock()
    b = bucket(100, 6000, clock)  # refills 100 tokens per second
    await b.acquire(6000)
    await b.acquire(1000)
    assert clock.now == 10  # waited for 1000 tokens to refill


async def test_settling_real_usage_returns_or_charges_the_difference() -> None:
    clock = Clock()
    b = bucket(100, 6000, clock)
    reserved = await b.acquire(6000)
    b.settle(reserved, 1000)  # used less: 5000 back
    await b.acquire(5000)
    assert clock.sleeps == [0.01]  # only the request spacing
    b.settle(5000, 8000)  # used more: bucket goes negative
    await b.acquire(100)
    assert clock.now > 30


async def test_an_oversized_call_still_passes_once_the_bucket_is_full() -> None:
    clock = Clock()
    b = bucket(100, 600, clock)
    assert await b.acquire(10_000) == 600


async def test_concurrent_callers_are_serialised() -> None:
    clock = Clock()
    b = bucket(1, 1_000_000, clock)
    await asyncio.gather(*(b.acquire(1) for _ in range(3)))
    assert clock.now == 2
