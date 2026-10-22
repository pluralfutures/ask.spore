"""In-memory stand-in for app.retrieval.ragflow.RagflowClient (content tests).

Mirrors the behaviour recorded from RAGFlow v0.27.2 that the content code depends
on: a duplicate dataset name is created as ``name(1)`` (findings R9), uploads
start ``UNSTART``, and parsing moves a document through ``RUNNING`` to a final
state. Tests script the final state per file name with ``outcomes``.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from app.retrieval.ragflow import RagflowDataset, RagflowDocument, RagflowError

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
