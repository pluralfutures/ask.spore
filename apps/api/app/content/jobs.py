"""The job queue (P1b-02): ``jobs`` rows run by ``ask-spore worker``.

Mirrors alembic revision 0014; the migration is authoritative. Operator-owned and
shared, outside tenant RLS: a payload carries identifiers and settings only (a check
constraint allows a fixed set of keys), and an outcome is ``status`` and ``error_code``
only, never an error text.

- ``enqueue`` adds a job inside the caller's transaction, so an approval and its job
  commit together; a second enqueue for the same subject while one is queued or
  running returns that job (one active job per subject, a partial unique index).
- ``claim`` takes the oldest due job with ``SELECT ... FOR UPDATE SKIP LOCKED``, counts
  the attempt and sets a lease (``locked_until``); a running job whose lease ran out
  (its worker died) is claimable again.
- ``finish`` records success, a retry with exponential backoff, or the final failure.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Text,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JobType = Literal["ingest_source", "withdraw_source", "crawl_site"]
JOB_TYPES: Final[tuple[JobType, ...]] = ("ingest_source", "withdraw_source", "crawl_site")
JobStatus = Literal["queued", "running", "succeeded", "failed"]
FINISHED: Final = frozenset({"succeeded", "failed"})
PAYLOAD_KEYS: Final = frozenset(
    {"source_id", "site_id", "add_tags", "downloadable", "parse_timeout"}
)
DEFAULT_MAX_ATTEMPTS: Final = 3
LEASE_SECONDS: Final = 300
BACKOFF_BASE_SECONDS: Final = 60
BACKOFF_MAX_SECONDS: Final = 3600

PayloadValue = str | int | float | bool | list[str]


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(f"type IN {JOB_TYPES}", name="type_valid"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="status_valid"
        ),
        Index(None, "status", "run_after"),
        # One queued or running job per subject (revision 0014).
        Index(
            "uq_jobs_one_active_per_subject",
            "type",
            text("(payload->>'source_id')"),
            text("(payload->>'site_id')"),
            text("(coalesce(payload->'add_tags', '[]'::jsonb))"),
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'queued'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, server_default=text("3"))
    error_code: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    type: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int

    @property
    def last_attempt(self) -> bool:
        return self.attempts >= self.max_attempts


@dataclass(frozen=True)
class JobState:
    id: uuid.UUID
    type: str
    status: str
    error_code: str | None
    attempts: int
    seconds: float  # from first start to finish, 0 when not finished


def backoff_seconds(attempts: int) -> int:
    """Delay before the next attempt after ``attempts`` tries: 1, 2, 4 ... minutes, capped."""
    return int(min(BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), BACKOFF_MAX_SECONDS))


async def enqueue(
    session: AsyncSession,
    job_type: JobType,
    payload: Mapping[str, PayloadValue],
    *,
    created_by: uuid.UUID | None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> uuid.UUID:
    """Add a job in the caller's transaction; the active job for the subject if one exists."""
    if job_type not in JOB_TYPES:
        raise ValueError(f"not a job type: {job_type}")
    unknown = set(payload) - PAYLOAD_KEYS
    if unknown:
        raise ValueError(f"payload keys not allowed: {', '.join(sorted(unknown))}")
    added = await session.scalar(
        insert(Job)
        .values(
            type=job_type, payload=dict(payload), created_by=created_by, max_attempts=max_attempts
        )
        .on_conflict_do_nothing()
        .returning(Job.id)
    )
    if added is not None:
        job_id: uuid.UUID = added
        return job_id
    subject = _subject(payload)
    active = [
        row.id
        for row in await session.execute(
            select(Job.id, Job.payload).where(
                Job.type == job_type, Job.status.in_(("queued", "running"))
            )
        )
        if _subject(row.payload) == subject
    ]
    if not active:  # finished between the insert and this read: enqueue afresh
        return await enqueue(
            session, job_type, payload, created_by=created_by, max_attempts=max_attempts
        )
    existing: uuid.UUID = active[0]
    return existing


def _subject(payload: Mapping[str, Any]) -> tuple[Any, Any, tuple[str, ...]]:
    """What the unique index compares: source, site and added tags."""
    tags = payload.get("add_tags")
    return (
        payload.get("source_id"),
        payload.get("site_id"),
        tuple(tags) if isinstance(tags, list) else (),
    )


async def claim(
    factory: async_sessionmaker[AsyncSession], *, lease_seconds: int = LEASE_SECONDS
) -> ClaimedJob | None:
    """Take the oldest due job, or a running one whose lease ran out; None when idle."""
    async with factory() as session, session.begin():
        job = await session.scalar(
            select(Job)
            .where(
                or_(
                    (Job.status == "queued") & (Job.run_after <= func.now()),
                    (Job.status == "running") & (Job.locked_until < func.now()),
                ),
                Job.attempts < Job.max_attempts,
            )
            .order_by(Job.run_after, Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        claimed = ClaimedJob(
            job.id, job.type, dict(job.payload), job.attempts + 1, job.max_attempts
        )
        await session.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(
                status="running",
                attempts=Job.attempts + 1,
                locked_until=func.now() + text(f"interval '{int(lease_seconds)} seconds'"),
                started_at=func.coalesce(Job.started_at, func.now()),
                updated_at=func.now(),
            )
        )
        return claimed


async def renew(
    factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID, lease_seconds: int
) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "running")
            .values(
                locked_until=func.now() + text(f"interval '{int(lease_seconds)} seconds'"),
                updated_at=func.now(),
            )
        )


async def finish(
    factory: async_sessionmaker[AsyncSession],
    job: ClaimedJob,
    *,
    error_code: str | None,
    retry: bool = False,
) -> JobStatus:
    """Record the outcome: succeeded, queued again after a backoff, or failed."""
    if error_code is None:
        values: dict[str, Any] = {"status": "succeeded", "error_code": None}
    elif retry and not job.last_attempt:
        values = {
            "status": "queued",
            "error_code": error_code,
            "run_after": func.now() + text(f"interval '{backoff_seconds(job.attempts)} seconds'"),
        }
    else:
        values = {"status": "failed", "error_code": error_code}
    if values["status"] != "queued":
        values["finished_at"] = func.now()
    async with factory() as session, session.begin():
        await session.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(locked_until=None, updated_at=func.now(), **values)
        )
    status: JobStatus = values["status"]
    return status


async def release(factory: async_sessionmaker[AsyncSession], job: ClaimedJob) -> None:
    """Give an interrupted job back to the queue without counting the attempt."""
    async with factory() as session, session.begin():
        await session.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == "running")
            .values(
                status="queued",
                attempts=func.greatest(Job.attempts - 1, 0),
                locked_until=None,
                updated_at=func.now(),
            )
        )


async def states(
    factory: async_sessionmaker[AsyncSession], job_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, JobState]:
    async with factory() as session:
        rows = await session.execute(
            select(
                Job.id,
                Job.type,
                Job.status,
                Job.error_code,
                Job.attempts,
                func.coalesce(func.extract("epoch", Job.finished_at - Job.started_at), 0).label(
                    "seconds"
                ),
            ).where(Job.id.in_(list(job_ids)))
        )
        return {
            r.id: JobState(r.id, r.type, r.status, r.error_code, r.attempts, float(r.seconds))
            for r in rows
        }


async def wait_for(
    factory: async_sessionmaker[AsyncSession],
    job_ids: Sequence[uuid.UUID],
    *,
    poll_interval: float = 5.0,
    give_up_after: float | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[uuid.UUID, JobState]:
    """Poll until every job has finished (or ``give_up_after`` seconds passed)."""
    deadline = None if give_up_after is None else clock() + give_up_after
    while True:
        found = await states(factory, job_ids)
        if all(s.status in FINISHED for s in found.values()) or (
            deadline is not None and clock() >= deadline
        ):
            return found
        await sleep(poll_interval)
