"""P0-07: contract tests for the RAGFlow client.

Responses under tests/fixtures/ragflow/ were recorded from the Compose RAGFlow
(v0.27.2) by driving this client against it; each test checks the request we send
and how we read the recorded response.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import load_settings
from app.retrieval import ragflow
from app.retrieval.protocol import Retriever
from app.retrieval.ragflow import RagflowClient, RagflowError, RagflowRetriever, page_or_slide
from app.retrieval.types import RetrievedChunk

FIXTURES = Path(__file__).parent / "fixtures" / "ragflow"
API_KEY = "test-ragflow-key"
DATASET_ID = "d2680670ca8111f18b280bc8b8cfdbb7"
DOCUMENT_ID = "d27287b2ca8111f18b280bc8b8cfdbb7"
QUESTION = "What was the levelised cost of fixed-bottom offshore wind in 2025?"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class Recorder:
    """Mock transport answering every request with one recorded response."""

    def __init__(self, body: Any = None, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self._respond: Callable[[httpx.Request], httpx.Response] = lambda _: httpx.Response(
            status, json=body
        )

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._respond(request)

        return httpx.MockTransport(handler)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def last_json(self) -> Any:
        return json.loads(self.last.content)


def client(recorder: Recorder) -> RagflowClient:
    return RagflowClient("http://ragflow:9380", API_KEY, 5, transport=recorder.transport())


def assert_authenticated(request: httpx.Request) -> None:
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert request.url.host == "ragflow"


async def test_create_dataset() -> None:
    rec = Recorder(fixture("create_dataset"))
    async with client(rec) as c:
        dataset = await c.create_dataset("ask-spore-sample-reports", "paper", "BAAI/bge-m3@Builtin")
    assert rec.last.method == "POST"
    assert rec.last.url.path == "/api/v1/datasets"
    assert_authenticated(rec.last)
    assert rec.last_json() == {
        "name": "ask-spore-sample-reports",
        "chunk_method": "paper",
        "permission": "me",
        "embedding_model": "BAAI/bge-m3@Builtin",
    }
    assert dataset.id == DATASET_ID
    assert dataset.chunk_method == "paper"
    assert dataset.embedding_model == "BAAI/bge-m3@Builtin"


async def test_list_datasets_reads_every_page() -> None:
    page = fixture("list_datasets")
    full = {**page, "data": [page["data"][0]] * ragflow.LIST_PAGE_SIZE}
    responses = iter([full, page])
    rec = Recorder()
    rec._respond = lambda _: httpx.Response(200, json=next(responses))
    async with client(rec) as c:
        datasets = await c.list_datasets()
    assert [r.url.params["page"] for r in rec.requests] == ["1", "2"]
    assert all(r.method == "GET" and r.url.path == "/api/v1/datasets" for r in rec.requests)
    # No name or id filter: RAGFlow answers "not found" with a permission error.
    assert all("name" not in r.url.params and "id" not in r.url.params for r in rec.requests)
    assert len(datasets) == ragflow.LIST_PAGE_SIZE + len(page["data"])
    assert DATASET_ID in {d.id for d in datasets}


async def test_upload_document_sends_multipart_file() -> None:
    rec = Recorder(fixture("upload_document"))
    async with client(rec) as c:
        document = await c.upload_document(DATASET_ID, "report.pdf", b"%PDF-1.4 synthetic")
    assert rec.last.method == "POST"
    assert rec.last.url.path == f"/api/v1/datasets/{DATASET_ID}/documents"
    assert rec.last.headers["Content-Type"].startswith("multipart/form-data")
    assert b'name="file"; filename="report.pdf"' in rec.last.content
    assert b"%PDF-1.4 synthetic" in rec.last.content
    assert document.id == DOCUMENT_ID
    assert document.dataset_id == DATASET_ID
    assert document.run == "UNSTART"
    assert not document.finished


async def test_set_document_chunk_method_patches_document() -> None:
    rec = Recorder(fixture("update_document"))
    async with client(rec) as c:
        await c.set_document_chunk_method(DATASET_ID, DOCUMENT_ID, "presentation")
    assert rec.last.method == "PATCH"
    assert rec.last.url.path == f"/api/v1/datasets/{DATASET_ID}/documents/{DOCUMENT_ID}"
    assert rec.last_json() == {"chunk_method": "presentation"}


async def test_start_parse() -> None:
    rec = Recorder(fixture("start_parse"))
    async with client(rec) as c:
        await c.start_parse(DATASET_ID, [DOCUMENT_ID])
    assert rec.last.method == "POST"
    assert rec.last.url.path == f"/api/v1/datasets/{DATASET_ID}/documents/parse"
    assert rec.last_json() == {"document_ids": [DOCUMENT_ID]}


@pytest.mark.parametrize(
    ("name", "run", "finished", "chunk_count"),
    [
        ("get_document_unstarted", "UNSTART", False, 0),
        ("get_document_running", "RUNNING", False, 0),
        ("get_document_done", "DONE", True, 5),
        ("get_document_failed", "FAIL", True, 0),
    ],
)
async def test_get_document_status(name: str, run: str, finished: bool, chunk_count: int) -> None:
    rec = Recorder(fixture(name))
    async with client(rec) as c:
        document = await c.get_document(DATASET_ID, DOCUMENT_ID)
    assert rec.last.method == "GET"
    assert rec.last.url.path == f"/api/v1/datasets/{DATASET_ID}/documents"
    assert rec.last.url.params["id"] == DOCUMENT_ID
    assert document.run == run
    assert document.finished is finished
    assert document.chunk_count == chunk_count


async def test_failed_document_carries_progress_message() -> None:
    rec = Recorder(fixture("get_document_failed"))
    async with client(rec) as c:
        document = await c.get_document(DATASET_ID, DOCUMENT_ID)
    assert "Insert chunk error" in document.progress_msg


async def test_retrieve_request_is_tool_free_and_maps_top_k_to_page_size() -> None:
    rec = Recorder(fixture("retrieve"))
    async with client(rec) as c:
        chunks = await c.retrieve_chunks(
            dataset_ids=[DATASET_ID], question=QUESTION, top_k=3, similarity_threshold=0.2
        )
    assert rec.last.method == "POST"
    assert rec.last.url.path == "/api/v1/retrieval"
    body = rec.last_json()
    assert body["dataset_ids"] == [DATASET_ID]
    assert body["question"] == QUESTION
    assert (body["page"], body["page_size"]) == (1, 3)
    assert body["similarity_threshold"] == 0.2
    assert body["knn_top_k"] == ragflow.KNN_TOP_K
    assert body["vector_similarity_weight"] == ragflow.DEFAULT_VECTOR_SIMILARITY_WEIGHT
    assert "top_k" not in body  # deprecated in v0.27.2
    # Nothing that would make RAGFlow send the question to an LLM of its own.
    assert body["keyword"] is False
    assert body["use_kg"] is False
    assert body["toc_enhance"] is False
    assert body["cross_languages"] == []
    assert "meta_data_filter" not in body
    assert "rerank_id" not in body
    assert body["include_knowledge_compilation"] is False
    assert "document_ids" not in body
    assert len(chunks) == 3
    first = chunks[0]
    assert isinstance(first, RetrievedChunk)
    assert first.dataset_id == DATASET_ID
    assert first.document_id == DOCUMENT_ID
    assert first.page_or_slide == 1
    assert "levelised cost" in first.text
    assert first.score == pytest.approx(0.3246, abs=1e-4)
    assert [c.score for c in chunks] == sorted((c.score for c in chunks), reverse=True)


async def test_retrieve_sends_the_configured_vector_weight() -> None:
    # P1b-15 e: [chat] vector_similarity_weight, through from_settings.
    from app.core.config import DEFAULT_CONFIG_DIR, load_settings
    from tests.test_config import ENV

    settings = load_settings(environ=ENV, config_dir=DEFAULT_CONFIG_DIR)
    chat = settings.models.chat.model_copy(update={"vector_similarity_weight": 0.55})
    tuned = replace(settings, models=settings.models.model_copy(update={"chat": chat}))
    rec = Recorder(fixture("retrieve"))
    async with RagflowClient.from_settings(tuned, transport=rec.transport()) as c:
        await c.retrieve_chunks(
            dataset_ids=[DATASET_ID], question=QUESTION, top_k=3, similarity_threshold=0.2
        )
    assert rec.last_json()["vector_similarity_weight"] == 0.55
    assert settings.models.chat.vector_similarity_weight == 0.3  # the repository's default


async def test_retrieve_with_nothing_above_threshold_returns_empty() -> None:
    rec = Recorder(fixture("retrieve_nothing"))
    async with client(rec) as c:
        chunks = await c.retrieve_chunks(
            dataset_ids=[DATASET_ID], question="zzqx", top_k=3, similarity_threshold=0.99
        )
    assert chunks == []


async def test_retrieve_with_no_datasets_makes_no_call() -> None:
    rec = Recorder(fixture("retrieve"))
    async with client(rec) as c:
        assert (
            await c.retrieve_chunks(
                dataset_ids=[], question=QUESTION, top_k=3, similarity_threshold=0.2
            )
            == []
        )
    assert rec.requests == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"positions": [[3, 1, 2, 3, 4], [4, 1, 2, 3, 4]]}, 3),
        ({"positions": []}, None),
        ({}, None),
        ({"positions": [[0, 0, 0, 0, 0]]}, None),
        ({"positions": [["x"]]}, None),
    ],
)
def test_page_or_slide(raw: dict[str, Any], expected: int | None) -> None:
    assert page_or_slide(raw) == expected


async def test_error_envelope_raises_with_code_and_message() -> None:
    rec = Recorder({"code": 102, "message": "You don't own the dataset abc."})
    async with client(rec) as c:
        with pytest.raises(RagflowError) as excinfo:
            await c.start_parse("abc", [DOCUMENT_ID])
    assert excinfo.value.code == 102
    assert excinfo.value.error_code == "ragflow_102"
    assert "You don't own the dataset abc." in str(excinfo.value)


async def test_retrieve_error_carries_no_detail() -> None:
    # RAGFlow messages can echo request content; retrieval errors must not.
    rec = Recorder({"code": 102, "message": f"something about {QUESTION}"})
    async with client(rec) as c:
        with pytest.raises(RagflowError) as excinfo:
            await c.retrieve_chunks(
                dataset_ids=["0" * 32], question=QUESTION, top_k=3, similarity_threshold=0.2
            )
    assert str(excinfo.value) == "RAGFlow retrieve failed (code 102)"
    assert fixture("error_retrieve_unknown_dataset")["code"] == 102


async def test_http_error_without_envelope() -> None:
    rec = Recorder()
    rec._respond = lambda _: httpx.Response(502, text="<html>bad gateway</html>")
    async with client(rec) as c:
        with pytest.raises(RagflowError) as excinfo:
            await c.list_datasets()
    assert excinfo.value.code == 502


async def test_timeout_and_unreachable_never_mention_the_key() -> None:
    for exc in (httpx.ReadTimeout("slow"), httpx.ConnectError("refused")):

        def handler(request: httpx.Request, exc: Exception = exc) -> httpx.Response:
            raise exc

        c = RagflowClient("http://ragflow:9380", API_KEY, 5, transport=httpx.MockTransport(handler))
        async with c:
            with pytest.raises(RagflowError) as excinfo:
                await c.list_datasets()
        assert excinfo.value.code in {"timeout", "unreachable"}
        assert API_KEY not in str(excinfo.value)
        assert excinfo.value.__cause__ is None


ENV = {
    "MISTRAL_API_KEY": "test-mistral-key",
    "SCALEWAY_API_KEY": "test-scaleway-key",
    "RAGFLOW_API_KEY": API_KEY,
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "PHASE0_BEARER_TOKEN": "test-bearer-token-0123456789abcdef",
    "AUTHENTIK_CLIENT_SECRET": "test-authentik-client-secret",
    "AUTHENTIK_API_TOKEN": "test-authentik-api-token",
}


async def test_module_retrieve_uses_config_and_logs_no_content(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = load_settings(environ=ENV)
    rec = Recorder(fixture("retrieve"))
    original = RagflowClient.from_settings

    def from_settings(s: Any, transport: Any = None) -> RagflowClient:
        assert s is settings
        return original(s, transport=rec.transport())

    monkeypatch.setattr(ragflow, "get_settings", lambda: settings)
    monkeypatch.setattr(RagflowClient, "from_settings", staticmethod(from_settings))

    chunks = await ragflow.retrieve(
        dataset_ids=[DATASET_ID], query=QUESTION, top_k=3, similarity_threshold=0.2
    )

    assert len(chunks) == 3
    assert rec.last.url.host == "ragflow"  # base URL from config/models.toml
    assert rec.last.headers["Authorization"] == f"Bearer {API_KEY}"
    out = capsys.readouterr().out
    line = json.loads(out.strip().splitlines()[-1])
    assert line["event"] == "ragflow.retrieve"
    assert line["chunk_count"] == 3
    assert QUESTION not in out
    assert all(chunk.text[:40] not in out for chunk in chunks)
    assert API_KEY not in out


async def test_module_retrieve_logs_error_code_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = load_settings(environ=ENV)
    rec = Recorder(fixture("error_retrieve_unknown_dataset"))
    original = RagflowClient.from_settings
    monkeypatch.setattr(ragflow, "get_settings", lambda: settings)
    monkeypatch.setattr(
        RagflowClient,
        "from_settings",
        staticmethod(lambda s, transport=None: original(s, transport=rec.transport())),
    )
    with pytest.raises(RagflowError):
        await ragflow.retrieve(
            dataset_ids=["0" * 32], query=QUESTION, top_k=3, similarity_threshold=0.2
        )
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line == {
        **line,
        "event": "ragflow.retrieve",
        "status": "error",
        "error_code": "ragflow_102",
    }
    assert QUESTION not in json.dumps(line)


async def test_ragflow_retriever_is_the_orchestrator_retriever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(environ=ENV)
    rec = Recorder(fixture("retrieve"))
    original = RagflowClient.from_settings
    monkeypatch.setattr(ragflow, "get_settings", lambda: settings)
    monkeypatch.setattr(
        RagflowClient,
        "from_settings",
        staticmethod(lambda s, transport=None: original(s, transport=rec.transport())),
    )
    retriever: Retriever = RagflowRetriever()

    chunks = await retriever.retrieve(
        dataset_ids=[DATASET_ID], query=QUESTION, top_k=3, similarity_threshold=0.2
    )

    assert len(chunks) == 3
    body = rec.last_json()
    assert (body["dataset_ids"], body["question"], body["page_size"]) == ([DATASET_ID], QUESTION, 3)
    assert body["similarity_threshold"] == 0.2


async def test_main_app_asks_through_ragflow(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without a retriever the API answers 503 retrieval_unavailable (Group C, P0-15).
    from app import main

    settings = load_settings(environ=ENV)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    async with main.app.router.lifespan_context(main.app):
        orchestrator = main.app.state.orchestrator
    assert isinstance(orchestrator._retriever, RagflowRetriever)


async def test_delete_documents_names_ids_never_delete_all() -> None:
    rec = Recorder(fixture("delete_documents"))
    async with client(rec) as c:
        await c.delete_documents(DATASET_ID, [DOCUMENT_ID])
        await c.delete_documents(DATASET_ID, [])
    assert len(rec.requests) == 1  # an empty list sends nothing
    assert rec.last.method == "DELETE"
    assert rec.last.url.path == f"/api/v1/datasets/{DATASET_ID}/documents"
    assert rec.last_json() == {"ids": [DOCUMENT_ID]}
