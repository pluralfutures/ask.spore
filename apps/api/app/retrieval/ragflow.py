"""RAGFlow HTTP API client (P0-07).

RAGFlow is internal: it is reached only on the Compose network at
``ragflow.base_url`` (config/models.toml, allow-listed at startup) with the service
key ``RAGFLOW_API_KEY`` from the environment. Nothing here is exposed through our
API, and dataset IDs are always passed in by server-side code that read them from
the ``datasets`` table, never from a request.

Uses ``httpx`` for every call rather than ``ragflow-sdk``: the SDK is synchronous
``requests`` with no timeout parameter, so it would block the API's event loop and
could hang without bound. See design/specs/phase-0-findings.md, section 2, for the
endpoints and parameters used and how they were confirmed against v0.27.2.

Exceptions never carry a query, chunk text or credential. Management calls
(datasets, documents) include RAGFlow's own error message, which names the
failing object; ``retrieve`` errors carry only the error code.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import log
from app.retrieval.types import RetrievedChunk

API_PREFIX = "/api/v1"
LIST_PAGE_SIZE = 100
MAX_ERROR_MESSAGE = 200

# Terminal values of a document's ``run`` field (RAGFlow TaskStatus names).
RUN_DONE = "DONE"
RUN_FAILED = "FAIL"
RUN_CANCELLED = "CANCEL"
TERMINAL_RUNS = frozenset({RUN_DONE, RUN_FAILED, RUN_CANCELLED})

# RAGFlow's ``knn_top_k`` (formerly ``top_k``) is the size of the vector-recall
# candidate pool, not the number of results; that is ``page_size``. Keep its default.
KNN_TOP_K = 1024
# Weight of vector vs. keyword similarity in RAGFlow's hybrid score: RAGFlow's default,
# used when no setting is given; the API and the harness pass [chat]
# vector_similarity_weight (P1b-15 e).
DEFAULT_VECTOR_SIMILARITY_WEIGHT = 0.3


class RagflowError(RuntimeError):
    """A RAGFlow call failed. ``code`` is RAGFlow's error code or the HTTP status."""

    def __init__(self, operation: str, code: int | str, detail: str | None = None) -> None:
        self.operation = operation
        self.code = code
        message = f"RAGFlow {operation} failed (code {code})"
        if detail:
            message += f": {detail[:MAX_ERROR_MESSAGE]}"
        super().__init__(message)

    @property
    def error_code(self) -> str:
        """Short identifier suitable for the ``error_code`` log field."""
        return f"ragflow_{self.code}"


@dataclass(frozen=True)
class RagflowDataset:
    id: str
    name: str
    chunk_method: str
    embedding_model: str
    document_count: int
    chunk_count: int


@dataclass(frozen=True)
class RagflowDocument:
    id: str
    dataset_id: str
    name: str
    chunk_method: str
    run: str
    progress: float
    progress_msg: str
    chunk_count: int

    @property
    def finished(self) -> bool:
        return self.run in TERMINAL_RUNS


def _dataset(raw: Mapping[str, Any]) -> RagflowDataset:
    return RagflowDataset(
        id=str(raw["id"]),
        name=str(raw["name"]),
        chunk_method=str(raw.get("chunk_method", "")),
        embedding_model=str(raw.get("embedding_model") or ""),
        document_count=int(raw.get("document_count") or 0),
        chunk_count=int(raw.get("chunk_count") or 0),
    )


def _document(raw: Mapping[str, Any], dataset_id: str) -> RagflowDocument:
    return RagflowDocument(
        id=str(raw["id"]),
        dataset_id=str(raw.get("dataset_id") or dataset_id),
        name=str(raw.get("name", "")),
        chunk_method=str(raw.get("chunk_method", "")),
        run=str(raw.get("run", "")).upper(),
        progress=float(raw.get("progress") or 0.0),
        progress_msg=str(raw.get("progress_msg") or ""),
        chunk_count=int(raw.get("chunk_count") or 0),
    )


def page_or_slide(raw: Mapping[str, Any]) -> int | None:
    """First page (PDF) or slide (PPTX) of a retrieved chunk, 1-based, if known.

    RAGFlow returns ``positions`` as ``[[page, x0, x1, top, bottom], ...]``. It also
    gives DOCX, HTML and Markdown chunks a pseudo-position ``[[1, 0, 0, 0, 0]]``,
    indistinguishable from slide 1 of a deck, so this value is meaningful only for
    ``pdf`` and ``pptx`` sources; callers that know the source type must ignore it
    for the others (findings R14).
    """
    positions = raw.get("positions")
    if isinstance(positions, list) and positions:
        first = positions[0]
        if isinstance(first, list | tuple) and first:
            try:
                page = int(first[0])
            except (TypeError, ValueError):
                return None
            return page if page > 0 else None
    return None


def _chunk(raw: Mapping[str, Any]) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(raw["id"]),
        document_id=str(raw["document_id"]),
        dataset_id=str(raw["dataset_id"]),
        text=str(raw.get("content") or ""),
        score=float(raw.get("similarity") or 0.0),
        page_or_slide=page_or_slide(raw),
    )


class RagflowClient:
    """Async client for the RAGFlow HTTP API. Use as an async context manager."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        vector_similarity_weight: float = DEFAULT_VECTOR_SIMILARITY_WEIGHT,
    ) -> None:
        self._vector_similarity_weight = vector_similarity_weight
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + API_PREFIX,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    @classmethod
    def from_settings(
        cls, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> RagflowClient:
        return cls(
            base_url=settings.models.ragflow.base_url,
            api_key=settings.secrets.ragflow_api_key.get_secret_value(),
            timeout_seconds=settings.models.ragflow.timeout_seconds,
            transport=transport,
            vector_similarity_weight=settings.models.chat.vector_similarity_weight,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        include_detail: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Send one request and return the envelope's ``data``; raise RagflowError otherwise.

        RAGFlow answers ``{"code": 0, "data": ...}`` on success and
        ``{"code": <n>, "message": ...}`` on failure, usually with HTTP 200.
        """
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise RagflowError(operation, "timeout") from None
        except httpx.TransportError:
            raise RagflowError(operation, "unreachable") from None
        try:
            body = response.json()
        except ValueError:
            raise RagflowError(operation, response.status_code) from None
        if not isinstance(body, dict):
            raise RagflowError(operation, response.status_code)
        code = body.get("code")
        if response.is_error or code != 0:
            detail = str(body.get("message") or "") if include_detail else None
            raise RagflowError(
                operation, code if code not in (None, 0) else response.status_code, detail
            )
        return body.get("data")

    # Datasets

    async def create_dataset(
        self, name: str, chunk_method: str, embedding_model: str | None = None
    ) -> RagflowDataset:
        payload: dict[str, Any] = {"name": name, "chunk_method": chunk_method, "permission": "me"}
        if embedding_model:
            payload["embedding_model"] = embedding_model
        data = await self._call("create_dataset", "POST", "/datasets", json=payload)
        return _dataset(data)

    async def list_datasets(self) -> list[RagflowDataset]:
        """Every dataset the service key can see.

        RAGFlow's ``id`` and ``name`` filters answer "not found" with the same error
        as "no permission" (findings, section 2), so callers filter this list instead.
        """
        datasets: list[RagflowDataset] = []
        page = 1
        while True:
            data = await self._call(
                "list_datasets",
                "GET",
                "/datasets",
                params={"page": page, "page_size": LIST_PAGE_SIZE, "orderby": "create_time"},
            )
            batch = [_dataset(item) for item in data or []]
            datasets += batch
            if len(batch) < LIST_PAGE_SIZE:
                return datasets
            page += 1

    # Documents

    async def upload_document(
        self, dataset_id: str, filename: str, content: bytes
    ) -> RagflowDocument:
        data = await self._call(
            "upload_document",
            "POST",
            f"/datasets/{dataset_id}/documents",
            files=[("file", (filename, content))],
        )
        if not isinstance(data, list) or len(data) != 1:
            raise RagflowError("upload_document", "unexpected_response")
        return _document(data[0], dataset_id)

    async def set_document_chunk_method(
        self, dataset_id: str, document_id: str, chunk_method: str
    ) -> None:
        await self._call(
            "update_document",
            "PATCH",
            f"/datasets/{dataset_id}/documents/{document_id}",
            json={"chunk_method": chunk_method},
        )

    async def start_parse(self, dataset_id: str, document_ids: Sequence[str]) -> None:
        await self._call(
            "start_parse",
            "POST",
            f"/datasets/{dataset_id}/documents/parse",
            json={"document_ids": list(document_ids)},
        )

    async def delete_documents(self, dataset_id: str, document_ids: Sequence[str]) -> None:
        """Delete the named documents and their chunks. Never ``delete_all``."""
        if not document_ids:
            return
        await self._call(
            "delete_documents",
            "DELETE",
            f"/datasets/{dataset_id}/documents",
            json={"ids": list(document_ids)},
        )

    async def get_document(self, dataset_id: str, document_id: str) -> RagflowDocument:
        data = await self._call(
            "get_document",
            "GET",
            f"/datasets/{dataset_id}/documents",
            params={"id": document_id, "page": 1, "page_size": 1},
        )
        docs = (data or {}).get("docs") or []
        if len(docs) != 1:
            raise RagflowError("get_document", "not_found")
        return _document(docs[0], dataset_id)

    # Retrieval

    async def retrieve_chunks(
        self,
        *,
        dataset_ids: Sequence[str],
        question: str,
        top_k: int,
        similarity_threshold: float,
    ) -> list[RetrievedChunk]:
        """Top ``top_k`` chunks across ``dataset_ids`` scoring at least the threshold.

        Every RAGFlow option that would send the question to an LLM configured inside
        RAGFlow (keyword extraction, cross-language rewriting, TOC enhancement,
        knowledge graph, automatic metadata filters) is explicitly off: retrieval is
        embedding plus keyword search only. LLM-compiled "knowledge compilation"
        chunks are excluded so every chunk is source text.
        """
        if not dataset_ids:
            return []
        payload = {
            "dataset_ids": list(dataset_ids),
            "question": question,
            "page": 1,
            "page_size": top_k,
            "similarity_threshold": similarity_threshold,
            "vector_similarity_weight": self._vector_similarity_weight,
            "knn_top_k": KNN_TOP_K,
            "keyword": False,
            "cross_languages": [],
            "toc_enhance": False,
            "use_kg": False,
            "highlight": False,
            "include_knowledge_compilation": False,
        }
        data = await self._call(
            "retrieve", "POST", "/retrieval", json=payload, include_detail=False
        )
        chunks = [_chunk(raw) for raw in (data or {}).get("chunks") or []]
        return chunks[:top_k]


async def retrieve(
    *, dataset_ids: list[str], query: str, top_k: int, similarity_threshold: float
) -> list[RetrievedChunk]:
    """Retrieve chunks for ``query`` from ``dataset_ids`` (the orchestrator's entry point).

    ``dataset_ids`` must come from the ``datasets`` table for the tenant's tags,
    never from a request.
    """
    started = time.monotonic()
    try:
        async with RagflowClient.from_settings(get_settings()) as client:
            chunks = await client.retrieve_chunks(
                dataset_ids=dataset_ids,
                question=query,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
            )
    except RagflowError as exc:
        log(
            "ragflow.retrieve",
            level="error",
            status="error",
            error_code=exc.error_code,
            latency_ms=round((time.monotonic() - started) * 1000),
        )
        raise
    log(
        "ragflow.retrieve",
        status="ok",
        chunk_count=len(chunks),
        latency_ms=round((time.monotonic() - started) * 1000),
    )
    return chunks


class RagflowRetriever:
    """The chat orchestrator's ``Retriever`` (app.retrieval.protocol), backed by RAGFlow."""

    async def retrieve(
        self, *, dataset_ids: list[str], query: str, top_k: int, similarity_threshold: float
    ) -> list[RetrievedChunk]:
        return await retrieve(
            dataset_ids=dataset_ids,
            query=query,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )
