"""P0-09, P1b-01: ingestion with the RAGFlow client faked and the test database real.

Each file goes through the register as the CLI sends it with ``--approve-as``: proposed
by an editor, approved by a reviewer (here the same person, holding both roles, as the
owner does), then ingested.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import cli
from app.content.fetch import Fetched
from app.content.ingest import (
    PARSE_TIMEOUT_SECONDS,
    IngestError,
    IngestResult,
    SourceFile,
    SourceMetadata,
    add_tags,
    from_fetched,
    ingest_source,
    load_path,
    upload_name,
)
from app.content.jobs import claim, finish
from app.content.submit import submit
from app.content.tags import load_tags
from app.core.config import DEFAULT_CONFIG_DIR
from app.core.db import create_engine, session_factory
from app.retrieval.ragflow import RagflowError
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.conftest import MigratedDatabase
from tests.ragflow_fake import FakeRagflow, Outcome

CORPUS = Path(__file__).resolve().parents[3] / "packages" / "eval" / "fixtures" / "corpus"
TAGS = load_tags(DEFAULT_CONFIG_DIR)
PDF = CORPUS / "tidewater-offshore-wind-2026.pdf"
PPTX = CORPUS / "kestrel-valley-storage-briefing.pptx"
DOCX = CORPUS / "brightwater-heat-pumps-note.docx"


def meta(*tags: str, title: str = "Tidewater Offshore Wind Outlook 2026") -> SourceMetadata:
    return SourceMetadata(
        tags=tags,
        title=title,
        publisher="Fictional Institute for Coastal Energy",
        licence_basis="CC BY 4.0",
        published_on=date(2026, 3, 1),
        canonical_url="https://example.org/tidewater-2026.pdf",
    )


Ingest = Callable[..., Awaitable[IngestResult]]


class Env:
    def __init__(
        self,
        fake: FakeRagflow,
        datasets: dict[str, str],
        user_id: UUID,
        content_root: Path,
        factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.factory = factory  # acts as the application role
        self.fake = fake
        self.datasets = datasets
        self.user_id = user_id  # holds both content roles
        self.content_root = content_root


async def reset_register(admin_conn: asyncpg.Connection) -> None:
    # Chat tests (P0-14, P0-15) share the session database and leave citations, which
    # restrict deleting the sources they cite.
    await admin_conn.execute("DELETE FROM citations")
    await admin_conn.execute("DELETE FROM downloads")
    await admin_conn.execute("DELETE FROM site_pages")
    await admin_conn.execute("DELETE FROM sources")
    await admin_conn.execute("DELETE FROM site_uploads")
    await admin_conn.execute("DELETE FROM sites")
    await admin_conn.execute("DELETE FROM datasets")


async def content_user(admin_conn: asyncpg.Connection, *roles: str) -> UUID:
    """The seeded internal editor, holding exactly ``roles``."""
    user_id: UUID = await admin_conn.fetchval(
        "SELECT id FROM users WHERE tenant_id = $1 AND email = 'editor@example.org'",
        INTERNAL_TENANT_ID,
    )
    await admin_conn.execute("DELETE FROM content_roles WHERE user_id = $1", user_id)
    for role in roles:
        await admin_conn.execute(
            "INSERT INTO content_roles (user_id, role) VALUES ($1, $2)", user_id, role
        )
    return user_id


@pytest.fixture
async def env(
    database: MigratedDatabase, admin_conn: asyncpg.Connection, tmp_path: Path
) -> AsyncIterator[tuple[Env, Ingest]]:
    await reset_register(admin_conn)
    fake = FakeRagflow()
    datasets: dict[str, str] = {}
    for tag, config in TAGS.items():
        dataset = fake.add_dataset(f"ask-spore-{tag}", config.chunk_method)
        datasets[tag] = dataset.id
        await admin_conn.execute(
            "INSERT INTO datasets (tag, ragflow_dataset_id) VALUES ($1, $2)", tag, dataset.id
        )
    engine = create_engine(database.sqlalchemy_url)

    # Act as the application role, as the CLI does, so grants are exercised.
    @event.listens_for(engine.sync_engine, "begin")
    def as_app_role(conn: Any) -> None:
        conn.exec_driver_sql("SET LOCAL ROLE askspore_app")

    factory = session_factory(engine)
    now = [0.0]

    async def fake_sleep(seconds: float) -> None:
        now[0] += seconds

    user_id = await content_user(admin_conn, "content_editor", "content_reviewer")
    root = tmp_path / "content"

    async def run(source: SourceFile, metadata: SourceMetadata, **kwargs: Any) -> IngestResult:
        """Submit as the CLI does, then run the queued job as the worker does."""
        content_root = kwargs.pop("content_root", root)
        timing = {
            "poll_interval": kwargs.pop("poll_interval", 3.0),
            "sleep": fake_sleep,
            "clock": lambda: now[0],
        }
        kwargs.setdefault("proposer_id", user_id)
        kwargs.setdefault("reviewer_id", user_id)
        submitted = await submit(
            factory, TAGS, source, metadata, content_root=content_root, **kwargs
        )
        if submitted.status != "queued":
            return submitted
        return await run_job(factory, fake, content_root, **timing)

    await reset_jobs(admin_conn)
    yield Env(fake, datasets, user_id, root, factory), run
    await engine.dispose()
    await reset_register(admin_conn)
    await reset_jobs(admin_conn)


async def reset_jobs(admin_conn: asyncpg.Connection) -> None:
    await admin_conn.execute("DELETE FROM jobs")


async def run_job(
    factory: async_sessionmaker[AsyncSession],
    fake: FakeRagflow,
    content_root: Path,
    **timing: Any,
) -> IngestResult:
    """Claim the next job and run it with the worker's ingestion functions, keeping the
    full result (document IDs, error text) for the assertions."""
    job = await claim(factory)
    assert job is not None and job.type == "ingest_source"
    source_id = UUID(job.payload["source_id"])
    parse_timeout = float(job.payload.get("parse_timeout") or PARSE_TIMEOUT_SECONDS)
    if job.payload.get("add_tags"):
        result = await add_tags(
            factory,
            fake,  # type: ignore[arg-type]
            TAGS,
            source_id,
            job.payload["add_tags"],
            downloadable=job.payload["downloadable"],
            content_root=content_root,
            parse_timeout=parse_timeout,
            **timing,
        )
    else:
        result = await ingest_source(
            factory,
            fake,  # type: ignore[arg-type]
            TAGS,
            source_id,
            content_root=content_root,
            parse_timeout=parse_timeout,
            **timing,
        )
    ok = result.status in ("ingested", "retagged", "duplicate")
    await finish(factory, job, error_code=None if ok else result.error_code)
    return result


async def source_row(admin_conn: asyncpg.Connection, source_id: UUID) -> asyncpg.Record:
    row = await admin_conn.fetchrow("SELECT * FROM sources WHERE id = $1", source_id)
    assert row is not None
    return row


async def test_pdf_is_registered_uploaded_parsed_and_recorded(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    e.fake.outcomes[".pdf"] = Outcome(chunk_count=5, polls_until_done=3)
    result = await run(load_path(PDF), meta("sample-reports"))

    assert result.status == "ingested"
    assert result.chunk_count == 5
    row = await source_row(admin_conn, result.source_id)
    assert row["status"] == "ingested"
    assert row["type"] == "pdf"
    assert row["title"] == "Tidewater Offshore Wind Outlook 2026"
    assert row["publisher"] == "Fictional Institute for Coastal Energy"
    assert row["licence_basis"] == "CC BY 4.0"
    assert row["published_on"] == date(2026, 3, 1)
    assert row["canonical_url"] == "https://example.org/tidewater-2026.pdf"
    assert row["tags"] == ["sample-reports"]
    assert row["chunk_count"] == 5
    assert row["error"] is None
    assert len(row["file_sha256"]) == 64
    document_ids = json.loads(row["ragflow_document_ids"])
    [(dataset_id, document_id)] = document_ids.items()
    assert dataset_id == e.datasets["sample-reports"]  # from the datasets table
    assert e.fake.parsed == [document_id]
    assert e.fake.chunk_methods == {}  # PDF uses the dataset's own method (paper)
    [(uploaded_to, name, content)] = e.fake.uploads
    assert uploaded_to == dataset_id
    assert name == upload_name(row["title"], result.source_id, "pdf")
    assert name.startswith("tidewater-offshore-wind-outlook-2026-")
    assert content == PDF.read_bytes()


async def test_pptx_in_analysis_gets_presentation_method_docx_does_not(
    env: tuple[Env, Ingest],
) -> None:
    e, run = env
    pptx = await run(load_path(PPTX), meta("sample-analysis", title="Kestrel briefing"))
    docx = await run(
        load_path(DOCX),
        SourceMetadata(
            **{
                **meta("sample-analysis", title="Brightwater note").__dict__,
                "canonical_url": "https://example.org/brightwater",
            }
        ),
    )
    assert (pptx.status, docx.status) == ("ingested", "ingested")
    [pptx_doc] = pptx.document_ids.values()
    [docx_doc] = docx.document_ids.values()
    assert e.fake.chunk_methods == {pptx_doc: "presentation"}
    assert docx_doc not in e.fake.chunk_methods


async def test_every_tag_gets_a_document_and_chunks_add_up(env: tuple[Env, Ingest]) -> None:
    e, run = env
    result = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    assert result.status == "ingested"
    assert set(result.document_ids) == {e.datasets["sample-reports"], e.datasets["sample-web"]}
    assert result.chunk_count == 2 * Outcome().chunk_count


async def test_parse_failure_records_error_and_removes_documents(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    e.fake.outcomes[".pdf"] = Outcome(
        run="FAIL", chunk_count=0, progress_msg="[ERROR] Insert chunk error: shard not active"
    )
    result = await run(load_path(PDF), meta("sample-reports"))

    assert result.status == "failed"
    assert result.error_code == "parse_failed"
    row = await source_row(admin_conn, result.source_id)
    assert row["status"] == "failed"
    # P2A-13: RAGFlow's progress message never reaches the row; the error is the code.
    assert "Insert chunk error" not in row["error"] and "shard" not in row["error"]
    assert row["error"] == result.error == "parse_failed: sample-reports FAIL"
    assert row["chunk_count"] is None
    assert json.loads(row["ragflow_document_ids"]) == {}
    assert e.fake.documents == {}  # nothing of a failed source stays retrievable


async def test_failure_in_one_tag_removes_documents_of_all_tags(
    env: tuple[Env, Ingest],
) -> None:
    e, run = env
    real_get = e.fake.get_document

    async def fail_web(dataset_id: str, document_id: str) -> Any:
        document = await real_get(dataset_id, document_id)
        if dataset_id == e.datasets["sample-web"] and document.finished:
            return document.__class__(**{**document.__dict__, "run": "CANCEL"})
        return document

    e.fake.get_document = fail_web  # type: ignore[method-assign]
    result = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    assert result.status == "failed"
    assert result.error == "parse_failed: sample-web CANCEL"
    assert len(e.fake.deleted) == 2
    assert e.fake.documents == {}


async def test_zero_chunks_is_a_failure(env: tuple[Env, Ingest]) -> None:
    e, run = env
    e.fake.outcomes[".pdf"] = Outcome(chunk_count=0)
    result = await run(load_path(PDF), meta("sample-reports"))
    assert (result.status, result.error_code) == ("failed", "no_chunks")


async def test_ragflow_error_is_recorded(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    e.fake.fail_upload = RagflowError("upload_document", 101, "file type not supported")
    result = await run(load_path(PDF), meta("sample-reports"))
    assert (result.status, result.error_code) == ("failed", "ragflow_101")
    row = await source_row(admin_conn, result.source_id)
    assert row["status"] == "failed"
    # P2A-13: the code only; RAGFlow's message text is not kept.
    assert row["error"] == "ragflow_101" and "not supported" not in row["error"]


async def test_parse_timeout(env: tuple[Env, Ingest]) -> None:
    e, run = env
    e.fake.outcomes[".pdf"] = Outcome(polls_until_done=10_000)
    result = await run(load_path(PDF), meta("sample-reports"), parse_timeout=30, poll_interval=3)
    assert (result.status, result.error_code) == ("failed", "parse_timeout")
    assert e.fake.documents == {}


async def test_a_ragflow_errors_text_never_reaches_the_source_row_or_the_log(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    """P2A-13: a RagflowError's detail is RAGFlow's own message; the row's error, the
    result and the log keep its code only, also when the clean-up fails too."""
    e, run = env
    secret = "Synthetic RAGFlow detail naming tidewater.pdf at /var/lib/ragflow/x"
    e.fake.fail_upload = RagflowError("upload_document", 102, secret)
    result = await run(load_path(PDF), meta("sample-reports"))
    row = await source_row(admin_conn, result.source_id)
    assert (result.status, result.error_code) == ("failed", "ragflow_102")
    assert row["error"] == result.error == "ragflow_102"

    e.fake.fail_upload = None
    e.fake.outcomes[".pdf"] = Outcome(run="FAIL", chunk_count=0, progress_msg=secret)
    e.fake.fail_delete = RagflowError("delete_documents", 500, secret)
    other = replace(meta("sample-reports"), title="Another synthetic report")
    failed = await run(replace(load_path(PDF), content=load_path(PDF).content + b" "), other)
    row = await source_row(admin_conn, failed.source_id)
    assert failed.error_code == "parse_failed"
    assert (
        row["error"]
        == failed.error
        == (
            "parse_failed: sample-reports FAIL; clean-up failed (ragflow_500), "
            "documents left in RAGFlow"
        )
    )
    out = capsys.readouterr().out
    for text in (row["error"], result.error or "", out):
        assert "Synthetic RAGFlow detail" not in text and "/var/lib" not in text


async def test_failed_clean_up_is_recorded_with_the_document_ids(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    e.fake.outcomes[".pdf"] = Outcome(run="FAIL", chunk_count=0)
    e.fake.fail_delete = RagflowError("delete_documents", "unreachable")
    result = await run(load_path(PDF), meta("sample-reports"))
    row = await source_row(admin_conn, result.source_id)
    assert row["status"] == "failed"
    assert row["error"] == (
        "parse_failed: sample-reports FAIL; clean-up failed (ragflow_unreachable), "
        "documents left in RAGFlow"
    )
    assert json.loads(row["ragflow_document_ids"]) == result.document_ids != {}


async def test_unexpected_error_still_marks_the_source_failed(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env

    async def boom(*_: Any) -> None:
        raise KeyError("surprise")

    e.fake.start_parse = boom  # type: ignore[method-assign]
    result = await run(load_path(PDF), meta("sample-reports"))
    row = await source_row(admin_conn, result.source_id)
    assert (row["status"], result.error_code) == ("failed", "internal_error")


async def test_already_ingested_file_is_a_duplicate(env: tuple[Env, Ingest]) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    uploads = len(e.fake.uploads)
    second = await run(load_path(PDF), meta("sample-reports"))
    assert second.status == "duplicate"
    assert second.source_id == first.source_id
    assert len(e.fake.uploads) == uploads


# --- P1a-04: an already-registered file linked into new tag datasets -----------------------


async def retag_events(admin_conn: asyncpg.Connection, source_id: UUID) -> list[dict[str, Any]]:
    rows = await admin_conn.fetch(
        "SELECT tenant_id, metadata FROM audit_events WHERE event = 'ingest.source_retagged'"
        " AND metadata->>'source_id' = $1",
        str(source_id),
    )
    return [{"tenant_id": r["tenant_id"], **json.loads(r["metadata"])} for r in rows]


async def test_duplicate_without_new_tags_uploads_nothing(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    uploads, parsed = len(e.fake.uploads), len(e.fake.parsed)
    second = await run(load_path(PDF), meta("sample-web"))  # a subset: nothing new
    assert (second.status, second.source_id, second.tags_added) == (
        "duplicate",
        first.source_id,
        (),
    )
    assert (len(e.fake.uploads), len(e.fake.parsed)) == (uploads, parsed)
    assert await retag_events(admin_conn, first.source_id) == []


async def test_duplicate_with_a_new_tag_is_linked_into_that_dataset_only(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    e.fake.outcomes[".pptx"] = Outcome(chunk_count=4)
    first = await run(load_path(PPTX), meta("sample-reports", title="Kestrel briefing"))
    [(reports_dataset, reports_doc)] = first.document_ids.items()
    uploads = len(e.fake.uploads)

    result = await run(
        load_path(PPTX), meta("sample-reports", "sample-analysis", title="Renamed in manifest")
    )
    assert (result.status, result.source_id) == ("retagged", first.source_id)
    assert result.tags_added == ("sample-analysis",)
    assert result.chunk_count == 4
    [(uploaded_to, name, content)] = e.fake.uploads[uploads:]
    assert uploaded_to == e.datasets["sample-analysis"]  # from the datasets table
    assert name == upload_name("Kestrel briefing", first.source_id, "pptx")  # the row's title
    assert content == PPTX.read_bytes()
    [(new_dataset, new_doc)] = result.document_ids.items()
    assert new_dataset == uploaded_to
    assert e.fake.parsed[-1] == new_doc
    assert e.fake.chunk_methods[new_doc] == "presentation"  # the per-type method, as before

    row = await source_row(admin_conn, first.source_id)
    assert row["status"] == "ingested"
    assert row["tags"] == ["sample-reports", "sample-analysis"]
    assert json.loads(row["ragflow_document_ids"]) == {
        reports_dataset: reports_doc,
        new_dataset: new_doc,
    }
    assert row["chunk_count"] == 8
    assert row["title"] == "Kestrel briefing"  # the rest of the register row is unchanged

    again = await run(load_path(PPTX), meta("sample-analysis", "sample-reports"))
    assert again.status == "duplicate"  # both tags are now the source's


async def test_failure_in_the_new_dataset_leaves_the_source_as_it_was(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    before = await source_row(admin_conn, first.source_id)
    e.fake.outcomes[".pdf"] = Outcome(run="FAIL", chunk_count=0, progress_msg="[ERROR] shard")

    result = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    assert (result.status, result.error_code) == ("failed", "parse_failed")
    assert result.source_id == first.source_id
    assert result.error == "parse_failed: sample-web FAIL"  # no RAGFlow message (P2A-13)
    [new_doc] = e.fake.deleted
    assert new_doc not in e.fake.documents  # the new document is gone
    assert result.document_ids == {}
    # The original document and mapping are untouched.
    assert set(e.fake.documents) == set(first.document_ids.values())
    after = await source_row(admin_conn, first.source_id)
    assert {k: after[k] for k in ("status", "tags", "ragflow_document_ids", "chunk_count")} == {
        k: before[k] for k in ("status", "tags", "ragflow_document_ids", "chunk_count")
    }
    assert after["error"] is None
    assert await retag_events(admin_conn, first.source_id) == []


async def test_upload_error_in_the_new_dataset_is_reported(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    e.fake.fail_upload = RagflowError("upload_document", 101, "file type not supported")
    result = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    assert (result.status, result.error_code) == ("failed", "ragflow_101")
    row = await source_row(admin_conn, first.source_id)
    assert (row["status"], row["tags"]) == ("ingested", ["sample-reports"])
    assert json.loads(row["ragflow_document_ids"]) == first.document_ids


async def test_retag_applies_the_rows_downloadable_and_audits_it(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, tmp_path: Path
) -> None:
    _, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    flagged = SourceMetadata(
        **{**meta("sample-reports", "sample-web").__dict__, "downloadable": True}
    )
    result = await run(load_path(PDF), flagged, content_root=tmp_path)
    assert result.status == "retagged"
    row = await source_row(admin_conn, first.source_id)
    assert row["downloadable"] is True
    assert row["stored_path"] is not None
    [audit] = await retag_events(admin_conn, first.source_id)
    assert audit["tenant_id"] == INTERNAL_TENANT_ID  # shared corpus: the platform tenant
    assert audit["before"] == {"tag_ids": ["sample-reports"], "downloadable": False}
    assert audit["after"] == {"tag_ids": ["sample-reports", "sample-web"], "downloadable": True}
    # Metadata only: no title, publisher, file name or dataset/document IDs.
    text = json.dumps(audit, default=str)
    for value in ("Tidewater", "Fictional", "tidewater", *result.document_ids.values()):
        assert value not in text

    # And back: a later row adding another tag with downloadable false closes the gate.
    plain = await run(load_path(PDF), meta("sample-analysis"), content_root=tmp_path)
    assert plain.status == "retagged"
    assert (await source_row(admin_conn, first.source_id))["downloadable"] is False


async def test_retag_takes_dataset_ids_from_the_datasets_table_only(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    uploads = len(e.fake.uploads)
    # SourceMetadata (a manifest row) has no field that could carry a dataset ID.
    assert not any("dataset" in name for name in SourceMetadata.__dataclass_fields__)
    await admin_conn.execute("DELETE FROM datasets WHERE tag = 'sample-web'")
    with pytest.raises(IngestError) as refused:
        await run(load_path(PDF), meta("sample-reports", "sample-web"))
    assert refused.value.code == "no_dataset"
    assert len(e.fake.uploads) == uploads
    row = await source_row(admin_conn, first.source_id)
    assert row["tags"] == ["sample-reports"]

    # A dataset re-synced under a new ID is the one used.
    replacement = e.fake.add_dataset("ask-spore-sample-web-new", "naive")
    await admin_conn.execute(
        "INSERT INTO datasets (tag, ragflow_dataset_id) VALUES ('sample-web', $1)", replacement.id
    )
    result = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    assert result.status == "retagged"
    assert list(result.document_ids) == [replacement.id]
    assert e.fake.uploads[-1][0] == replacement.id


# --- P1a-14: our own stored copy and the download flag -------------------------------------


async def test_file_is_stored_by_hash_and_the_flag_recorded(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, tmp_path: Path
) -> None:
    _, run = env
    downloadable = SourceMetadata(**{**meta("sample-reports").__dict__, "downloadable": True})
    result = await run(load_path(PDF), downloadable, content_root=tmp_path)
    row = await source_row(admin_conn, result.source_id)
    sha = row["file_sha256"]
    assert row["downloadable"] is True
    assert row["stored_path"] == f"{sha[:2]}/{sha}.pdf"
    stored = tmp_path / row["stored_path"]
    assert stored.read_bytes() == PDF.read_bytes()
    # Named by hash only: the original file name appears nowhere under the root.
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == [f"{sha}.pdf"]  # noqa: ASYNC240

    plain = await run(load_path(DOCX), meta("sample-reports"), content_root=tmp_path)
    row = await source_row(admin_conn, plain.source_id)
    assert row["downloadable"] is False  # the default
    assert row["stored_path"] is not None  # stored anyway, so the operator can open the gate


async def test_every_proposed_file_is_staged_for_the_worker(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    result = await run(load_path(PDF), meta("sample-reports"))
    row = await source_row(admin_conn, result.source_id)
    sha = row["file_sha256"]
    # The worker reads the file from the content store, never from the proposer's disk.
    assert (e.content_root / f"{sha[:2]}/{sha}.pdf").read_bytes() == PDF.read_bytes()
    assert (row["stored_path"], row["downloadable"]) == (f"{sha[:2]}/{sha}.pdf", False)


async def test_duplicate_gets_its_stored_copy_but_keeps_its_flag(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    _, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    await admin_conn.execute("UPDATE sources SET stored_path = NULL")  # ingested before P1a-14
    again = SourceMetadata(**{**meta("sample-reports").__dict__, "downloadable": True})
    second = await run(load_path(PDF), again)
    assert (second.status, second.source_id) == ("duplicate", first.source_id)
    row = await source_row(admin_conn, first.source_id)
    assert row["stored_path"] is not None
    assert row["downloadable"] is False  # changed only in the operator console, audited


async def test_pages_are_not_stored_and_cannot_be_downloadable(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, tmp_path: Path
) -> None:
    _, run = env
    page = SourceFile("page.md", "markdown", b"# Synthetic page\n\nSynthetic text.")
    result = await run(page, meta("sample-web"), content_root=tmp_path)
    row = await source_row(admin_conn, result.source_id)
    assert row["stored_path"] is None  # staged for the worker, never downloadable
    staged = [p.name for p in tmp_path.rglob("*") if p.is_file()]  # noqa: ASYNC240
    assert staged == [f"{row['file_sha256']}.markdown"]
    with pytest.raises(IngestError) as refused:
        other = SourceFile("other.md", "markdown", b"# Another synthetic page")
        flagged = SourceMetadata(**{**meta("sample-web").__dict__, "downloadable": True})
        await run(other, flagged, content_root=tmp_path)
    assert refused.value.code == "not_downloadable"


@pytest.mark.parametrize(
    ("tags", "code"),
    [((), "no_tag"), (("sample-reports", "no-such-tag"), "unknown_tag")],
)
async def test_bad_tags_record_nothing(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, tags: tuple[str, ...], code: str
) -> None:
    e, run = env
    with pytest.raises(IngestError) as excinfo:
        await run(load_path(PDF), meta(*tags))
    assert excinfo.value.code == code
    assert await admin_conn.fetchval("SELECT count(*) FROM sources") == 0
    assert e.fake.uploads == []


async def test_unsynced_tag_records_nothing(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    _, run = env
    await admin_conn.execute("DELETE FROM datasets WHERE tag = 'sample-web'")
    with pytest.raises(IngestError, match="datasets sync"):
        await run(load_path(PDF), meta("sample-web"))
    assert await admin_conn.fetchval("SELECT count(*) FROM sources") == 0


async def test_empty_metadata_is_rejected(env: tuple[Env, Ingest]) -> None:
    _, run = env
    with pytest.raises(IngestError, match="--publisher"):
        await run(
            load_path(PDF),
            SourceMetadata(tags=("sample-reports",), title="T", publisher=" ", licence_basis="x"),
        )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("tidewater-offshore-wind-2026.pdf", "pdf"),
        ("brightwater-heat-pumps-note.docx", "docx"),
        ("kestrel-valley-storage-briefing.pptx", "pptx"),
        ("ferrow-hydrogen-pilot.html", "html"),
        ("hollin-grid-tariffs.md", "markdown"),
    ],
)
def test_load_path_detects_supported_types(name: str, expected: str) -> None:
    assert load_path(CORPUS / name).type == expected


def test_load_path_rejects_other_types(tmp_path: Path) -> None:
    path = tmp_path / "data.xlsx"
    path.write_bytes(b"x")
    with pytest.raises(IngestError, match="unsupported file type"):
        load_path(path)


def fetched(content_type: str, content: bytes, headers: dict[str, str] | None = None) -> Fetched:
    return Fetched(
        url="https://example.org/reports/outlook.pdf?utm_source=x",
        status=200,
        content_type=content_type,
        headers=httpx.Headers(headers or {}),
        content=content,
    )


def test_from_fetched_uses_media_type() -> None:
    source = from_fetched(fetched("application/pdf", b"%PDF-1.4"))
    assert (source.filename, source.type) == ("outlook.pdf", "pdf")
    html = from_fetched(fetched("text/html", b"<html><p>hi</p></html>"))
    assert (html.filename, html.type) == ("outlook.html", "html")


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        ({"TDM-Reservation": "1"}, b"<html></html>"),
        ({}, b'<html><head><meta name="tdm-reservation" content="1"></head></html>'),
    ],
)
def test_from_fetched_refuses_tdm_reserved_content(headers: dict[str, str], body: bytes) -> None:
    with pytest.raises(IngestError) as excinfo:
        from_fetched(fetched("text/html", body, headers))
    assert excinfo.value.code == "tdm_reserved"
    # The message reaches the CLI's exit text: a code and words, never the URL (P1c-04).
    assert "://" not in str(excinfo.value)


def test_from_fetched_messages_carry_no_url() -> None:
    with pytest.raises(IngestError) as excinfo:
        from_fetched(fetched("text/html", b"", {}))
    assert excinfo.value.code == "empty" and "://" not in str(excinfo.value)


def test_tdm_reservation_zero_is_allowed() -> None:
    body = b'<html><meta name="tdm-reservation" content="0"></html>'
    assert from_fetched(fetched("text/html", body, {"tdm-reservation": "0"})).type == "html"


def test_cli_logs_ids_and_status_only(capsys: pytest.CaptureFixture[str]) -> None:
    result = IngestResult(
        source_id=UUID(int=7),
        status="failed",
        error_code="parse_failed",
        error="Tidewater Offshore Wind Outlook 2026: parse FAIL: secret body text",
    )
    cli._log_ingest(result)
    out = capsys.readouterr().out
    line = json.loads(out)
    assert line["event"] == "ingest.result"
    assert (line["status"], line["error_code"]) == ("failed", "parse_failed")
    assert line["source_id"] == str(UUID(int=7))
    assert "Tidewater" not in out and "secret body text" not in out


def test_cli_ingest_arguments() -> None:
    args = cli.build_parser().parse_args(
        [
            "ingest",
            str(PDF),
            "--tag",
            "sample-reports",
            "--tag",
            "sample-web",
            "--title",
            "T",
            "--publisher",
            "P",
            "--licence",
            "own work",
            "--published-on",
            "2026-03-01",
        ]
    )
    assert args.tag == ["sample-reports", "sample-web"]
    assert args.published_on == date(2026, 3, 1)
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["ingest", str(PDF), "--title", "T"])
