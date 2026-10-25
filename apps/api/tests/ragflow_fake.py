"""In-memory stand-in for app.retrieval.ragflow.RagflowClient (content tests).

Mirrors the behaviour recorded from RAGFlow v0.27.2 that the content code depends
on: a duplicate dataset name is created as ``name(1)`` (findings R9), uploads
start ``UNSTART``, and parsing moves a document through ``RUNNING`` to a final
state. Tests script the final state per file name with ``outcomes``.

P2A-01: the document status toggle as recorded in the P2A-00 probe. ``PATCH`` with an
integer ``enabled`` sets the status and with it the availability of the document's
chunks; a boolean is refused with code 102; a ``status`` field is ignored; a document
under another dataset is refused. ``retrieve_chunks`` returns the chunks of parsed,
enabled documents only, as RAGFlow's retrieval filters ``available_int = 1``.
``transport()`` serves the toggle over HTTP so a real ``RagflowClient`` can drive it and
a test can read the payload RAGFlow received (``patch_payloads``).
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from app.retrieval.ragflow import RagflowDataset, RagflowDocument, RagflowError
from app.retrieval.types import RetrievedChunk

_ids = (f"{n:032x}" for n in itertools.count(1))


@dataclass
class Outcome:
    run: str = "DONE"
    chunk_count: int = 3
    progress_msg: str = ""
    polls_until_done: int = 1


@dataclass
class FakeRagflow:
    datasets: dict[str, RagflowDataset] = field(default_factory=dict)
    documents: dict[str, RagflowDocument] = field(default_factory=dict)
    uploads: list[tuple[str, str, bytes]] = field(default_factory=list)
    chunk_methods: dict[str, str] = field(default_factory=dict)
    parsed: list[str] = field(default_factory=list)
    outcomes: dict[str, Outcome] = field(default_factory=dict)
    fail_upload: RagflowError | None = None
    created: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    fail_delete: RagflowError | None = None
    # P2A-01: every toggle as (dataset_id, document_id, enabled), the raw PATCH bodies
    # received over ``transport()``, toggles that fail per dataset, datasets whose toggle
    # answers success with the old status, and every retrieval's dataset IDs.
    toggles: list[tuple[str, str, int]] = field(default_factory=list)
    patch_payloads: list[dict[str, Any]] = field(default_factory=list)
    fail_toggle: dict[str, RagflowError] = field(default_factory=dict)
    fail_enable: dict[str, RagflowError] = field(default_factory=dict)  # enabled 1 only
    stale_status: set[str] = field(default_factory=set)
    retrievals: list[list[str]] = field(default_factory=list)
    _polls: dict[str, int] = field(default_factory=dict)

    def add_dataset(
        self, name: str, chunk_method: str, embedding_model: str = "BAAI/bge-m3@Builtin"
    ) -> RagflowDataset:
        taken = {d.name for d in self.datasets.values()}
        final = name
        for n in itertools.count(1):
            if final not in taken:
                break
            final = f"{name}({n})"
        dataset = RagflowDataset(
            id=next(_ids),
            name=final,
            chunk_method=chunk_method,
            embedding_model=embedding_model,
            document_count=0,
            chunk_count=0,
        )
        self.datasets[dataset.id] = dataset
        return dataset

    # RagflowClient interface

    async def create_dataset(
        self, name: str, chunk_method: str, embedding_model: str | None = None
    ) -> RagflowDataset:
        dataset = self.add_dataset(name, chunk_method, embedding_model or "")
        self.created.append(dataset.name)
        return dataset

    async def list_datasets(self) -> list[RagflowDataset]:
        return list(self.datasets.values())

    async def upload_document(
        self, dataset_id: str, filename: str, content: bytes
    ) -> RagflowDocument:
        if self.fail_upload is not None:
            raise self.fail_upload
        if dataset_id not in self.datasets:
            raise RagflowError("upload_document", 102, f"You don't own the dataset {dataset_id}.")
        self.uploads.append((dataset_id, filename, content))
        document = RagflowDocument(
            id=next(_ids),
            dataset_id=dataset_id,
            name=filename,
            chunk_method=self.datasets[dataset_id].chunk_method,
            run="UNSTART",
            progress=0.0,
            progress_msg="",
            chunk_count=0,
            enabled=True,
        )
        self.documents[document.id] = document
        return document

    async def set_document_chunk_method(
        self, dataset_id: str, document_id: str, chunk_method: str
    ) -> None:
        self.chunk_methods[document_id] = chunk_method
        self.documents[document_id] = replace(
            self.documents[document_id], chunk_method=chunk_method
        )

    async def start_parse(self, dataset_id: str, document_ids: Sequence[str]) -> None:
        for document_id in document_ids:
            self.parsed.append(document_id)
            self._polls[document_id] = 0
            self.documents[document_id] = replace(self.documents[document_id], run="RUNNING")

    async def delete_documents(self, dataset_id: str, document_ids: Sequence[str]) -> None:
        if self.fail_delete is not None:
            raise self.fail_delete
        for document_id in document_ids:
            if document_id not in self.documents:
                # RAGFlow answers an unknown document with a data error (code 102).
                raise RagflowError("delete_documents", 102, "document not found")
            self.deleted.append(document_id)
            del self.documents[document_id]

    def patch_document(self, dataset_id: str, document_id: str, body: dict[str, Any]) -> Any:
        """RAGFlow's ``PATCH …/documents/<id>`` for the status, as the probe recorded it:
        the response envelope (always HTTP 200)."""
        self.patch_payloads.append(dict(body))
        document = self.documents.get(document_id)
        if document is None or document.dataset_id != dataset_id:
            return {"code": 102, "message": "the dataset doesn't own the document"}
        if "enabled" in body:
            value = body["enabled"]
            if not isinstance(value, int) or isinstance(value, bool) or value not in (0, 1):
                return {"code": 102, "message": "Field: <enabled> - Message: <invalid>"}
            error = self.fail_toggle.get(dataset_id) or (
                self.fail_enable.get(dataset_id) if value == 1 else None
            )
            if error is not None:
                return {"code": error.code, "message": "toggle failed"}
            self.toggles.append((dataset_id, document_id, value))
            if dataset_id not in self.stale_status:
                document = replace(document, enabled=bool(value))
                self.documents[document_id] = document
        # Any other field (``status`` among them) is ignored, as by RAGFlow.
        return {
            "code": 0,
            "data": {
                "id": document.id,
                "dataset_id": dataset_id,
                "name": document.name,
                "location": document.name,
                "run": document.run,
                "chunk_count": document.chunk_count,
                "status": "1" if document.enabled is not False else "0",
            },
        }

    def transport(self) -> httpx.MockTransport:
        """The toggle over HTTP for a real ``RagflowClient`` (other paths answer 404)."""

        def handler(request: httpx.Request) -> httpx.Response:
            parts = request.url.path.strip("/").split("/")
            if (
                request.method == "PATCH"
                and len(parts) == 6
                and parts[:3] == ["api", "v1", "datasets"]
                and parts[4] == "documents"
            ):
                body = json.loads(request.content or b"{}")
                return httpx.Response(200, json=self.patch_document(parts[3], parts[5], body))
            return httpx.Response(404, json={"code": 404, "message": "not found"})

        return httpx.MockTransport(handler)

    async def set_document_enabled(
        self, dataset_id: str, document_id: str, *, enabled: bool
    ) -> None:
        """The client method over the fake, with the client's checks."""
        reply = self.patch_document(dataset_id, document_id, {"enabled": 1 if enabled else 0})
        if reply["code"] != 0:
            raise RagflowError("set_document_enabled", reply["code"])
        if (reply["data"]["status"] == "1") is not enabled:
            raise RagflowError("set_document_enabled", "status_mismatch")

    async def list_documents(self, dataset_id: str) -> list[RagflowDocument]:
        return [d for d in self.documents.values() if d.dataset_id == dataset_id]

    async def retrieve_chunks(
        self,
        *,
        dataset_ids: Sequence[str],
        question: str,
        top_k: int,
        similarity_threshold: float,
    ) -> list[RetrievedChunk]:
        """Every chunk of every parsed, enabled document in ``dataset_ids``."""
        self.retrievals.append(list(dataset_ids))
        chunks = [
            RetrievedChunk(
                chunk_id=f"{document.id}-{n}",
                document_id=document.id,
                dataset_id=document.dataset_id,
                text=f"Synthetic passage {n} of {document.name}.",
                score=0.9,
                page_or_slide=n + 1,
            )
            for document in self.documents.values()
            if document.dataset_id in dataset_ids
            and document.run == "DONE"
            and document.enabled is not False
            for n in range(document.chunk_count)
        ]
        return chunks[:top_k]

    async def retrieve(
        self, *, dataset_ids: list[str], query: str, top_k: int, similarity_threshold: float
    ) -> list[RetrievedChunk]:
        """``app.retrieval.protocol.Retriever`` over the fake (the chat orchestrator)."""
        return await self.retrieve_chunks(
            dataset_ids=dataset_ids,
            question=query,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )

    async def get_document(self, dataset_id: str, document_id: str) -> RagflowDocument:
        if document_id not in self.documents:
            raise RagflowError("get_document", "not_found")
        document = self.documents[document_id]
        if document.run == "RUNNING":
            # Keyed by a suffix of the uploaded file name, e.g. ".pptx".
            outcome = next(
                (o for suffix, o in self.outcomes.items() if document.name.endswith(suffix)),
                Outcome(),
            )
            self._polls[document_id] += 1
            if self._polls[document_id] >= outcome.polls_until_done:
                document = replace(
                    document,
                    run=outcome.run,
                    chunk_count=outcome.chunk_count,
                    progress=1.0 if outcome.run == "DONE" else -1.0,
                    progress_msg=outcome.progress_msg,
                )
                self.documents[document_id] = document
        return document
