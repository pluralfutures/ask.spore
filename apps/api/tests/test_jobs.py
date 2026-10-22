"""P1b-02: the job queue and the ingestion worker (RAGFlow faked, database real)."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from app import cli
from app.content import worker
from app.content.ingest import IngestResult, load_path
from app.content.jobs import (
    BACKOFF_MAX_SECONDS,
    backoff_seconds,
    claim,
    enqueue,
    finish,
    states,
)
from app.content.register import approve, propose
from app.content.submit import settle
from app.core.db import tenant_session
from app.core.logging import format_line
from app.retrieval.ragflow import RagflowError
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.ragflow_fake import Outcome
from tests.test_ingest import DOCX, PDF, TAGS, Env, Ingest, env, meta, source_row

__all__ = ["env"]  # the fixture, imported for its use here

COMPOSE = Path(__file__).resolve().parents[3] / "infra" / "compose.dev.yml"


def context(e: Env) -> worker.Context:
    return worker.Context(
        factory=e.factory,
        client=e.fake,  # type: ignore[arg-type]
        tags=TAGS,
        content_root=e.content_root,
        parse_poll_interval=0,
    )


async def approved(e: Env, path: Path = PDF) -> tuple[UUID, UUID]:
    submission = await propose(
        e.factory,
        TAGS,
        load_path(path),
        meta("sample-reports"),
        content_root=e.content_root,
        proposer_id=e.user_id,
    )
    job_id = await approve(e.factory, submission.source_id, e.user_id)
    return submission.source_id, job_id


async def job_row(admin_conn: asyncpg.Connection, job_id: UUID) -> asyncpg.Record:
    row = await admin_conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
    assert row is not None
    return row


async def test_approval_enqueues_exactly_one_job(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    source_id, job_id = await approved(e)
    rows = await admin_conn.fetch("SELECT * FROM jobs")
    assert [r["id"] for r in rows] == [job_id]
    [row] = rows
    assert (row["type"], row["status"], row["attempts"], row["created_by"]) == (
        "ingest_source",
        "queued",
        0,
        e.user_id,
    )
    assert json.loads(row["payload"]) == {"source_id": str(source_id)}  # identifiers only
    # Enqueueing again for the same source, or re-running the CLI, adds nothing.
    async with tenant_session(e.factory, INTERNAL_TENANT_ID) as session:
        again = await enqueue(
            session, "ingest_source", {"source_id": str(source_id)}, created_by=None
        )
    assert again == job_id
    rerun = await run(load_path(PDF), meta("sample-reports"))
    assert rerun.source_id == source_id
    assert await admin_conn.fetchval("SELECT count(*) FROM jobs") == 1
    assert e.fake.uploads != []  # the harness ran that one job


async def test_the_worker_ingests_an_approved_source(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    e, _ = env
    e.fake.outcomes[".pdf"] = Outcome(chunk_count=6)
    source_id, job_id = await approved(e)
    ctx = context(e)
    assert await worker.run_once(e.factory, worker.handlers(ctx)) is True
    assert await worker.run_once(e.factory, worker.handlers(ctx)) is False  # queue empty
    row = await source_row(admin_conn, source_id)
    assert (row["status"], row["chunk_count"]) == ("ingested", 6)
    job = await job_row(admin_conn, job_id)
    assert (job["status"], job["attempts"], job["error_code"]) == ("succeeded", 1, None)
    assert job["finished_at"] is not None and job["locked_until"] is None
    [line] = [json.loads(x) for x in capsys.readouterr().out.splitlines() if "job.finished" in x]
    assert {k: line[k] for k in ("job_id", "job_type", "status", "attempts", "source_id")} == {
        "job_id": str(job_id),
        "job_type": "ingest_source",
        "status": "succeeded",
        "attempts": 1,
        "source_id": str(source_id),
    }


async def test_a_failed_job_records_an_error_code_and_no_body(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    e, _ = env
    e.fake.outcomes[".pdf"] = Outcome(
        run="FAIL", chunk_count=0, progress_msg="[ERROR] Synthetic secret body text of the PDF"
    )
    source_id, job_id = await approved(e)
    await worker.run_once(e.factory, worker.handlers(context(e)))

    job = await job_row(admin_conn, job_id)
    assert (job["status"], job["error_code"]) == ("failed", "parse_failed")
    as_text = json.dumps(dict(job), default=str)
    for leak in ("secret body text", "Tidewater", "Fictional", "tidewater"):
        assert leak not in as_text
    # The register row keeps the detail for the console; the job and the log do not.
    assert (await source_row(admin_conn, source_id))["status"] == "failed"
    out = capsys.readouterr().out
    assert "secret body text" not in out and "Tidewater" not in out
    [line] = [json.loads(x) for x in out.splitlines() if "job.finished" in x]
    assert (line["status"], line["error_code"], line["level"]) == (
        "failed",
        "parse_failed",
        "error",
    )


async def test_a_job_for_an_unapproved_source_is_refused(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    submission = await propose(
        e.factory,
        TAGS,
        load_path(PDF),
        meta("sample-reports"),
        content_root=e.content_root,
        proposer_id=e.user_id,
    )
    async with tenant_session(e.factory, INTERNAL_TENANT_ID) as session:
        job_id = await enqueue(
            session, "ingest_source", {"source_id": str(submission.source_id)}, created_by=None
        )
    await worker.run_once(e.factory, worker.handlers(context(e)))
    job = await job_row(admin_conn, job_id)
    assert (job["status"], job["error_code"], job["attempts"]) == ("failed", "not_approved", 1)
    assert (await source_row(admin_conn, submission.source_id))["status"] == "proposed"
    assert e.fake.uploads == []


async def test_an_unavailable_ragflow_is_retried_with_backoff_then_fails(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    e.fake.fail_upload = RagflowError("upload_document", "unreachable")
    source_id, job_id = await approved(e)
    handlers = worker.handlers(context(e))
    await worker.run_once(e.factory, handlers)
    job = await job_row(admin_conn, job_id)
    assert (job["status"], job["attempts"], job["error_code"]) == (
        "queued",
        1,
        "ragflow_unreachable",
    )
    assert await admin_conn.fetchval("SELECT run_after > now() + interval '50 seconds' FROM jobs")
    assert (await source_row(admin_conn, source_id))["status"] == "approved"  # still waiting
    assert await worker.run_once(e.factory, handlers) is False  # not due yet

    for attempt in (2, 3):
        await admin_conn.execute("UPDATE jobs SET run_after = now()")
        await worker.run_once(e.factory, handlers)
        assert (await job_row(admin_conn, job_id))["attempts"] == attempt
    job = await job_row(admin_conn, job_id)
    assert (job["status"], job["error_code"]) == ("failed", "ragflow_unreachable")
    row = await source_row(admin_conn, source_id)
    assert (row["status"], row["ragflow_document_ids"]) == ("failed", "{}")


def test_backoff_doubles_and_is_capped() -> None:
    assert [backoff_seconds(n) for n in (1, 2, 3, 4)] == [60, 120, 240, 480]
    assert backoff_seconds(30) == BACKOFF_MAX_SECONDS


async def test_a_job_whose_worker_died_is_claimed_again(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    _, job_id = await approved(e)
    first = await claim(e.factory)
    assert first is not None and first.id == job_id
    assert await claim(e.factory) is None  # leased
    await admin_conn.execute("UPDATE jobs SET locked_until = now() - interval '1 second'")
    second = await claim(e.factory)
    assert second is not None and (second.id, second.attempts) == (job_id, 2)


async def test_an_interrupted_run_is_cleaned_up_before_the_next_upload(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    source_id, _ = await approved(e)
    # A worker stopped after the upload: the mapping it recorded points at a document.
    stale = await e.fake.upload_document(e.datasets["sample-reports"], "stale.pdf", b"x")
    await admin_conn.execute(
        "UPDATE sources SET ragflow_document_ids = $2::jsonb WHERE id = $1",
        source_id,
        json.dumps({e.datasets["sample-reports"]: stale.id}),
    )
    await worker.run_once(e.factory, worker.handlers(context(e)))
    assert stale.id in e.fake.deleted
    row = await source_row(admin_conn, source_id)
    assert row["status"] == "ingested"
    assert stale.id not in json.loads(row["ragflow_document_ids"]).values()


async def test_a_stopped_worker_puts_the_job_back(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    _, job_id = await approved(e)
    started = asyncio.Event()

    async def slow(_: Any) -> worker.Outcome:
        started.set()
        await asyncio.sleep(3600)
        return worker.Outcome()

    task = asyncio.create_task(worker.run_once(e.factory, {"ingest_source": slow}))
    await started.wait()
    assert (await job_row(admin_conn, job_id))["status"] == "running"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    job = await job_row(admin_conn, job_id)
    assert (job["status"], job["attempts"], job["locked_until"]) == ("queued", 0, None)


async def test_job_types_without_a_handler_fail_with_a_code(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    async with tenant_session(e.factory, INTERNAL_TENANT_ID) as session:
        job_id = await enqueue(
            session, "crawl_site", {"site_id": str(uuid.uuid4())}, created_by=None
        )
    await worker.run_once(e.factory, worker.handlers(context(e)))
    job = await job_row(admin_conn, job_id)
    assert (job["status"], job["error_code"]) == ("failed", "unsupported_job_type")


async def test_a_crashing_handler_fails_the_job_not_the_worker(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    _, job_id = await approved(e)

    async def boom(_: Any) -> worker.Outcome:
        raise KeyError("Synthetic secret body text")

    assert await worker.run_once(e.factory, {"ingest_source": boom}) is True
    job = await job_row(admin_conn, job_id)
    assert (job["status"], job["error_code"]) == ("failed", "internal_error")


async def test_payloads_hold_identifiers_only(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, app_conn: asyncpg.Connection
) -> None:
    e, _ = env
    async with tenant_session(e.factory, INTERNAL_TENANT_ID) as session:
        with pytest.raises(ValueError, match="payload keys not allowed"):
            await enqueue(session, "ingest_source", {"text": "body"}, created_by=None)  # type: ignore[dict-item]
        with pytest.raises(ValueError, match="not a job type"):
            await enqueue(session, "send_mail", {}, created_by=None)  # type: ignore[arg-type]
    for payload in ('{"source_id": "x", "content": "body"}', '"a string"', '{"query": "q"}'):
        with pytest.raises(asyncpg.CheckViolationError):
            await app_conn.execute(
                "INSERT INTO jobs (type, payload) VALUES ('ingest_source', $1::jsonb)", payload
            )
    with pytest.raises(asyncpg.CheckViolationError):
        await app_conn.execute(
            "INSERT INTO jobs (type, payload, status, error_code) "
            "VALUES ('ingest_source', '{}', 'failed', 'RAGFlow said: some body text')"
        )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("DELETE FROM jobs")


async def test_settle_reports_what_the_jobs_did(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    e.fake.outcomes[".pdf"] = Outcome(chunk_count=4)
    e.fake.outcomes[".docx"] = Outcome(run="FAIL", chunk_count=0)
    pdf_source, pdf_job = await approved(e)
    docx_source, docx_job = await approved(e, DOCX)
    queued = [
        IngestResult(source_id=pdf_source, status="queued", job_id=pdf_job),
        IngestResult(source_id=docx_source, status="queued", job_id=docx_job),
        IngestResult(source_id=uuid.uuid4(), status="proposed"),
    ]
    polls = 0

    async def run_worker_while_waiting(_: float) -> None:
        nonlocal polls
        polls += 1
        await worker.run_once(e.factory, worker.handlers(context(e)))

    settled = await settle(e.factory, queued, sleep=run_worker_while_waiting)
    assert [(r.status, r.chunk_count, r.error_code) for r in settled] == [
        ("ingested", 4, None),
        ("failed", 0, "parse_failed"),
        ("proposed", 0, None),
    ]
    assert polls == 2
    found = await states(e.factory, [pdf_job])
    assert found[pdf_job].seconds >= 0


def test_log_lines_take_job_fields_as_scalars_only() -> None:
    line = json.loads(
        format_line("job.finished", job_id=str(uuid.uuid4()), job_type="ingest_source", attempts=2)
    )
    assert (line["job_type"], line["attempts"]) == ("ingest_source", 2)
    from app.core.logging import ForbiddenLogField

    with pytest.raises(ForbiddenLogField):
        format_line("job.finished", job_type="x" * 200)
    with pytest.raises(ForbiddenLogField):
        format_line("job.finished", attempts=[1, 2])  # type: ignore[arg-type]


def test_cli_worker_and_wait_flags() -> None:
    args = cli.build_parser().parse_args(["worker", "--once", "--poll-interval", "1"])
    assert (args.once, args.poll_interval) == (True, 1.0)
    args = cli.build_parser().parse_args(
        ["ingest-manifest", "m.csv", "--approve-as", "a", "--wait"]
    )
    assert (args.wait, args.approve_as) == (True, "a")


def test_compose_runs_the_worker_from_the_api_image_without_ports() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    block = re.search(r"\n  worker:\n(.*?)\n\n", text, re.S)
    assert block is not None
    worker_block = block.group(1)
    assert "context: ../apps/api" in worker_block
    assert 'command: ["ask-spore", "worker"]' in worker_block
    assert "ports:" not in worker_block  # nothing published
    assert "content:/srv/ask-spore/content" in worker_block
    assert "- ragflow" in worker_block and "authentik" not in worker_block


async def test_finish_without_error_succeeds(env: tuple[Env, Ingest]) -> None:
    e, _ = env
    _, job_id = await approved(e)
    job = await claim(e.factory)
    assert job is not None
    assert await finish(e.factory, job, error_code=None) == "succeeded"
    assert (await states(e.factory, [job_id]))[job_id].status == "succeeded"
