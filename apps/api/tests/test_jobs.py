"""P1b-02: the job queue and the ingestion worker (RAGFlow faked, database real)."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import replace
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
from app.content.register import approve, approve_retag, propose, request_withdrawal
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
    # Nor does the register row (P2A-13): its error is the code.
    row = await source_row(admin_conn, source_id)
    assert row["status"] == "failed" and row["error"].startswith("parse_failed: ")
    assert "secret" not in row["error"]
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


async def test_an_interrupted_retag_is_cleaned_up_before_the_next_upload(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    """P1c-14 (findings 1b A1-11): a re-tag cut off by a stopped worker leaves its new
    document mapped on the row, under a tag the row does not hold; the next attempt
    deletes it from RAGFlow before uploading again, as an interrupted first ingestion."""
    e, _ = env
    source_id, _ = await approved(e)
    ctx = context(e)
    await worker.run_once(e.factory, worker.handlers(ctx))
    [(reports_dataset, reports_doc)] = json.loads(
        (await source_row(admin_conn, source_id))["ragflow_document_ids"]
    ).items()
    await approve_retag(e.factory, source_id, e.user_id, ["sample-web"], downloadable=False)

    e.fake.outcomes[".pdf"] = Outcome(chunk_count=4, polls_until_done=10**9)  # never parses
    web = e.datasets["sample-web"]
    parsing = asyncio.Event()
    start_parse = e.fake.start_parse

    async def started(dataset_id: str, document_ids: list[str]) -> None:
        await start_parse(dataset_id, document_ids)
        if dataset_id == web:  # after the upload was recorded on the row
            parsing.set()

    e.fake.start_parse = started  # type: ignore[method-assign]
    task = asyncio.create_task(worker.run_once(e.factory, worker.handlers(ctx)))
    await asyncio.wait_for(parsing.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    row = await source_row(admin_conn, source_id)
    assert row["tags"] == ["sample-reports"]  # the re-tag did not finish
    stale = json.loads(row["ragflow_document_ids"])[web]
    assert stale in e.fake.documents and stale not in e.fake.deleted

    e.fake.start_parse = start_parse  # type: ignore[method-assign]
    e.fake.outcomes[".pdf"] = Outcome(chunk_count=4)
    await worker.run_once(e.factory, worker.handlers(ctx))  # the job was put back
    assert stale in e.fake.deleted and stale not in e.fake.documents
    row = await source_row(admin_conn, source_id)
    mapping = json.loads(row["ragflow_document_ids"])
    assert row["tags"] == ["sample-reports", "sample-web"]
    assert mapping[reports_dataset] == reports_doc and mapping[web] != stale
    assert set(mapping.values()) <= set(e.fake.documents)
    assert [doc.id for doc in e.fake.documents.values() if doc.dataset_id == web] == [mapping[web]]


async def test_a_failed_retag_unmaps_what_it_deleted_and_keeps_what_it_could_not(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    source_id, _ = await approved(e)
    ctx = context(e)
    await worker.run_once(e.factory, worker.handlers(ctx))
    before = json.loads((await source_row(admin_conn, source_id))["ragflow_document_ids"])
    await approve_retag(e.factory, source_id, e.user_id, ["sample-web"], downloadable=False)
    e.fake.outcomes[".pdf"] = Outcome(run="FAIL", chunk_count=0, progress_msg="[ERROR] x")
    e.fake.fail_delete = RagflowError("delete_documents", "unreachable")
    await worker.run_once(e.factory, worker.handlers(ctx))
    row = await source_row(admin_conn, source_id)
    mapping = json.loads(row["ragflow_document_ids"])
    web = e.datasets["sample-web"]
    assert row["tags"] == ["sample-reports"] and set(mapping) == {*before, web}
    left = mapping[web]  # its clean-up failed: still mapped, so nothing loses track of it

    # A withdrawal deletes it with the rest; the next re-tag would have, too.
    e.fake.fail_delete = None
    await request_withdrawal(e.factory, source_id, e.user_id, reason="synthetic")
    await admin_conn.execute("UPDATE jobs SET run_after = now()")
    while await worker.run_once(e.factory, worker.handlers(ctx)):
        pass
    assert left in e.fake.deleted and left not in e.fake.documents
    assert (await source_row(admin_conn, source_id))["status"] == "withdrawn"


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
    registry = worker.handlers(context(e))
    del registry["crawl_site"]
    await worker.run_once(e.factory, registry)
    job = await job_row(admin_conn, job_id)
    assert (job["status"], job["error_code"]) == ("failed", "unsupported_job_type")
    # P1b-04 registers the handler: a crawl of a site that does not exist is refused.
    async with tenant_session(e.factory, INTERNAL_TENANT_ID) as session:
        job_id = await enqueue(
            session, "crawl_site", {"site_id": str(uuid.uuid4())}, created_by=None
        )
    await worker.run_once(e.factory, worker.handlers(context(e)))
    job = await job_row(admin_conn, job_id)
    assert (job["status"], job["error_code"]) == ("failed", "no_site")


def test_crawl_and_mail_handlers_register_together(tmp_path: Path) -> None:
    # Integration of P1b-04 and P1b-11: one worker runs crawls and platform mail.
    from app.mail.jobs import MailContext

    ctx = worker.Context(
        factory=None,  # type: ignore[arg-type]
        client=None,  # type: ignore[arg-type]
        tags=TAGS,
        content_root=tmp_path,
        mail=MailContext(factory=None, config=None, config_dir=tmp_path, sender=None),  # type: ignore[arg-type]
    )
    assert set(worker.handlers(ctx)) == {
        "ingest_source",
        "withdraw_source",
        "crawl_site",
        "import_crawl",
        "send_mail",
        "purge_retention",
    }
    assert "send_mail" not in worker.handlers(replace(ctx, mail=None))


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
            await enqueue(session, "purge_tenant", {}, created_by=None)  # type: ignore[arg-type]
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


# --- P1c-04: jobs are scoped by the payload's tenant -------------------------------------


async def _mail_job(admin_conn: asyncpg.Connection, tenant_id: UUID) -> UUID:
    payload = {"template": "invitation", "tenant_id": str(tenant_id), "user_id": str(uuid.uuid4())}
    job_id: UUID = await admin_conn.fetchval(
        "INSERT INTO jobs (type, payload) VALUES ('send_mail', $1::jsonb) RETURNING id",
        json.dumps(payload),
    )
    return job_id


async def _visible(conn: asyncpg.Connection, tenant_id: UUID | None) -> set[UUID]:
    async with conn.transaction():
        if tenant_id is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
        return {r["id"] for r in await conn.fetch("SELECT id FROM jobs")}


async def test_a_tenant_scoped_session_reads_no_job_of_another_tenant(
    admin_conn: asyncpg.Connection, app_conn: asyncpg.Connection
) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    mail_a, mail_b = await _mail_job(admin_conn, a), await _mail_job(admin_conn, b)
    shared = await admin_conn.fetchval(
        "INSERT INTO jobs (type, payload) VALUES ('ingest_source', $1::jsonb) RETURNING id",
        json.dumps({"source_id": str(uuid.uuid4())}),
    )
    # Tenant A's scope: its own job and the jobs that name no tenant; zero rows of B's.
    assert await _visible(app_conn, a) == {mail_a, shared}
    assert await _visible(app_conn, b) == {mail_b, shared}
    async with app_conn.transaction():
        await app_conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(a))
        assert await app_conn.fetchval("SELECT count(*) FROM jobs WHERE id = $1", mail_b) == 0
        updated = await app_conn.execute(
            "UPDATE jobs SET status = 'failed', error_code = 'x' WHERE id = $1", mail_b
        )
        assert updated == "UPDATE 0"
    assert (await job_row(admin_conn, mail_b))["status"] == "queued"
    # The worker's and the CLI's unscoped sessions see every job, as before.
    assert {mail_a, mail_b, shared} <= await _visible(app_conn, None)


async def test_a_tenant_scoped_session_cannot_queue_a_job_for_another_tenant(
    app_conn: asyncpg.Connection,
) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    payload = {"template": "invitation", "tenant_id": str(b), "user_id": str(uuid.uuid4())}
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        async with app_conn.transaction():
            await app_conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(a))
            await app_conn.execute(
                "INSERT INTO jobs (type, payload) VALUES ('send_mail', $1::jsonb)",
                json.dumps(payload),
            )


async def test_the_operator_role_reads_every_job_even_when_scoped(
    admin_conn: asyncpg.Connection, app_conn: asyncpg.Connection
) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    jobs = {await _mail_job(admin_conn, a), await _mail_job(admin_conn, b)}
    await app_conn.execute("SET ROLE askspore_operator")
    assert jobs <= await _visible(app_conn, a)
    assert jobs <= await _visible(app_conn, None)


async def test_jobs_rls_is_forced_with_both_policies(admin_conn: asyncpg.Connection) -> None:
    row = await admin_conn.fetchrow(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'jobs'"
    )
    assert (row["relrowsecurity"], row["relforcerowsecurity"]) == (True, True)
    policies = await admin_conn.fetch(
        "SELECT policyname, roles::text[] AS roles FROM pg_policies WHERE tablename = 'jobs' "
        "ORDER BY policyname"
    )
    # P1c-04's two policies, plus P1c-07's user-removal role (migration 0051).
    assert [(p["policyname"], p["roles"]) for p in policies] == [
        ("operator_console", ["askspore_operator"]),
        ("tenant_scope", ["public"]),
        ("user_removal", ["askspore_user_removal"]),
    ]
