"""Dataset bootstrap (P0-08): one RAGFlow dataset per tag in config/tags.toml.

``sync_datasets`` is idempotent. For each configured tag it ensures the RAGFlow
dataset ``ask-spore-<tag>`` exists with the tag's chunking method and the configured
embedding model, and that the ``datasets`` table maps the tag to it. It never
deletes, renames or reconfigures a dataset: anything it cannot reconcile safely is
reported and left for a person, because re-creating a dataset orphans every
document already ingested into it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import Dataset, Source
from app.content.tags import TagConfig, dataset_name
from app.retrieval.ragflow import RagflowClient, RagflowDataset

SyncStatus = Literal[
    "ok",  # mapped, exists, configured as expected
    "created",  # created in RAGFlow and mapped
    "adopted",  # existed in RAGFlow under the expected name, now mapped
    "missing",  # mapped, but the dataset no longer exists in RAGFlow
    "mismatch",  # exists, but its chunk method or embedding model differs from config
    "ambiguous",  # several RAGFlow datasets carry the expected name
    "unconfigured",  # mapped, but the tag is no longer in config/tags.toml
]
FAILED: frozenset[SyncStatus] = frozenset({"missing", "mismatch", "ambiguous"})


@dataclass(frozen=True)
class SyncResult:
    tag: str
    status: SyncStatus
    dataset_id: str | None

    @property
    def failed(self) -> bool:
        return self.status in FAILED


def _matches(dataset: RagflowDataset, config: TagConfig, embedding_model: str) -> bool:
    return (
        dataset.chunk_method == config.chunk_method and dataset.embedding_model == embedding_model
    )


async def sync_datasets(
    session: AsyncSession,
    client: RagflowClient,
    tags: Mapping[str, TagConfig],
    embedding_model: str,
) -> list[SyncResult]:
    """Reconcile RAGFlow datasets and the ``datasets`` table with ``tags``.

    Writes go through ``session``; the caller commits.
    """
    mapped = {row.tag: row for row in (await session.scalars(select(Dataset))).all()}
    remote = await client.list_datasets()
    by_id = {d.id: d for d in remote}
    results: list[SyncResult] = []

    for tag, config in sorted(tags.items()):
        row = mapped.get(tag)
        if row is not None:
            existing = by_id.get(row.ragflow_dataset_id)
            if existing is None:
                status: SyncStatus = "missing"
            elif not _matches(existing, config, embedding_model):
                status = "mismatch"
            else:
                status = "ok"
            results.append(SyncResult(tag, status, row.ragflow_dataset_id))
            continue

        # Exact name only: RAGFlow answers a duplicate create with "<name>(1)" (R9).
        named = [d for d in remote if d.name == dataset_name(tag)]
        if len(named) > 1:
            results.append(SyncResult(tag, "ambiguous", None))
            continue
        if named:
            dataset = named[0]
            if not _matches(dataset, config, embedding_model):
                results.append(SyncResult(tag, "mismatch", dataset.id))
                continue
            status = "adopted"
        else:
            dataset = await client.create_dataset(
                dataset_name(tag), config.chunk_method, embedding_model
            )
            status = "created"
        session.add(Dataset(tag=tag, ragflow_dataset_id=dataset.id))
        await session.flush()
        results.append(SyncResult(tag, status, dataset.id))

    for tag in sorted(set(mapped) - set(tags)):
        results.append(SyncResult(tag, "unconfigured", mapped[tag].ragflow_dataset_id))
    return results


@dataclass(frozen=True)
class DatasetCount:
    """P1c-10: one mapped tag's dataset as RAGFlow counts it (documents, chunks)."""

    tag: str
    dataset_id: str
    documents: int | None  # None: the mapped dataset is not in RAGFlow
    chunks: int | None


async def dataset_counts(session: AsyncSession, client: RagflowClient) -> list[DatasetCount]:
    """RAGFlow's own document and chunk counts for every mapped tag, by tag; metadata
    only. The deploy script compares them with the figures before the deploy."""
    mapped = (await session.scalars(select(Dataset).order_by(Dataset.tag))).all()
    remote = {d.id: d for d in await client.list_datasets()}
    counts: list[DatasetCount] = []
    for row in mapped:
        found = remote.get(row.ragflow_dataset_id)
        counts.append(
            DatasetCount(
                row.tag,
                row.ragflow_dataset_id,
                found.document_count if found else None,
                found.chunk_count if found else None,
            )
        )
    return counts


DocumentState = Literal["enabled", "disabled", "missing"]


@dataclass(frozen=True)
class StatusMismatch:
    """P2A-01: a source's RAGFlow document whose status disagrees with the register:
    an ingested source's document disabled (or gone), a paused source's enabled."""

    source_id: UUID
    tag: str
    dataset_id: str
    expected: DocumentState
    found: DocumentState


async def status_mismatches(session: AsyncSession, client: RagflowClient) -> list[StatusMismatch]:
    """Compare every ingested or paused source's documents in the mapped datasets with
    RAGFlow's status; one listing per dataset, metadata only. A pause or resume whose
    undo failed, or a change made by hand in RAGFlow, shows up here."""
    datasets = {
        row.ragflow_dataset_id: row.tag
        for row in (await session.scalars(select(Dataset).order_by(Dataset.tag))).all()
    }
    rows = (
        await session.execute(
            select(Source.id, Source.status, Source.ragflow_document_ids)
            .where(Source.status.in_(("ingested", "paused")))
            .order_by(Source.id)
        )
    ).all()
    wanted = {dataset_id for row in rows for dataset_id in (row.ragflow_document_ids or {})}
    remote: dict[str, dict[str, bool | None]] = {}
    for dataset_id in sorted(wanted & set(datasets)):
        remote[dataset_id] = {d.id: d.enabled for d in await client.list_documents(dataset_id)}
    mismatches: list[StatusMismatch] = []
    for row in rows:
        mapping = row.ragflow_document_ids
        if not isinstance(mapping, dict):
            continue
        expected: DocumentState = "disabled" if row.status == "paused" else "enabled"
        for dataset_id, document_id in sorted(mapping.items()):
            if dataset_id not in remote:
                continue  # not a synced dataset (Phase 0 mapping): nothing to compare
            enabled = remote[dataset_id].get(str(document_id), "missing")
            found: DocumentState = (
                "missing" if enabled == "missing" else "disabled" if enabled is False else "enabled"
            )
            if found != expected:
                mismatches.append(
                    StatusMismatch(row.id, datasets[dataset_id], dataset_id, expected, found)
                )
    return mismatches
