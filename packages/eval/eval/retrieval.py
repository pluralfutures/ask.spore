"""The orchestrator's retrieval step, run on its own (P0-18).

Mirrors ``app.chat.orchestrator`` steps 4 to 6 with the same building blocks and
the same ``[chat]`` parameters: the package of the eval workspace (P1a-04: a
workspace of the internal tenant, ``research`` by default) with its dataset IDs from
the ``datasets`` table (never from input), RAGFlow retrieval with ``top_k`` and the similarity
threshold, the provenance join, and ``select_context`` (threshold, de-duplication,
token cap). Eval questions are first turns, so there is no rewrite: the query is
the question, as in the orchestrator.

Read-only: the database session is never committed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.chat.context import select_context
from app.chat.package import Package, provenance_by_document, workspace_package
from app.content.models import Source
from app.core.config import Settings
from app.core.db import set_tenant
from app.retrieval.ragflow import RagflowClient, RagflowError
from app.tenancy.models import INTERNAL_TENANT_ID
from app.tenancy.workspaces import Workspace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eval.metrics import hit_at
from eval.records import RankedChunk, RetrievalRecord, SourceRef

HIT_KS = (5, 10)
DEFAULT_WORKSPACE = "research"  # seeded by alembic revision 0007


class WorkspaceMissing(LookupError):
    """The internal tenant has no workspace with the requested slug."""


@dataclass(frozen=True)
class RetrievalOutput:
    record: RetrievalRecord
    chunk_texts: dict[str, str]  # chunk_id -> text, for the judge; never written out


class RetrievalStep:
    def __init__(
        self,
        settings: Settings,
        client: RagflowClient,
        db: async_sessionmaker[AsyncSession],
        workspace: str = DEFAULT_WORKSPACE,
    ) -> None:
        self._chat = settings.models.chat
        self._workspace = workspace
        self._client = client
        self._db = db
        self.workspace_id: str | None = None
        self.package = Package((), (), "")
        self.register: list[SourceRef] = []

    @property
    def depth(self) -> int:
        """Chunks requested: enough for hit@10 even when ``top_k`` is smaller."""
        return max(self._chat.top_k, *HIT_KS)

    async def prepare(self) -> None:
        async with self._db() as session:
            # The eval user is an internal-tenant user; workspaces are tenant-scoped (RLS).
            await set_tenant(session, INTERNAL_TENANT_ID)
            workspace_id = await session.scalar(
                select(Workspace.id).where(Workspace.slug == self._workspace)
            )
            if workspace_id is None:
                raise WorkspaceMissing(self._workspace)
            self.workspace_id = str(workspace_id)
            self.package = await workspace_package(session, workspace_id)
            rows = await session.execute(
                select(Source.id, Source.canonical_url).where(Source.status != "withdrawn")
            )
            self.register = [SourceRef(str(row.id), row.canonical_url) for row in rows]
            await session.rollback()

    def unknown_expected(self, expected: Sequence[str]) -> list[str]:
        known = {r.source_id for r in self.register} | {r.canonical_url for r in self.register}
        return sorted(set(expected) - known)

    async def run(self, question: str, expected: Sequence[str]) -> RetrievalOutput:
        record = RetrievalRecord()
        try:
            chunks = await self._client.retrieve_chunks(
                dataset_ids=self.package.dataset_ids,
                question=question,
                top_k=self.depth,
                similarity_threshold=self._chat.similarity_threshold,
            )
        except RagflowError as exc:
            record.error = exc.error_code
            return RetrievalOutput(record, {})
        chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
        async with self._db() as session:
            provenance = await provenance_by_document(
                session, sorted({c.document_id for c in chunks})
            )
            await session.rollback()
        for rank, chunk in enumerate(chunks, start=1):
            source = provenance.get(chunk.document_id)
            record.chunks.append(
                RankedChunk(
                    rank=rank,
                    chunk_id=chunk.chunk_id,
                    score=round(chunk.score, 4),
                    source_id=str(source.source_id) if source else None,
                    canonical_url=source.canonical_url if source else None,
                )
            )
        # What the orchestrator would put in the prompt, from its own top_k.
        context = select_context(
            chunks[: self._chat.top_k],
            provenance,
            dataset_ids=self.package.dataset_ids,
            similarity_threshold=self._chat.similarity_threshold,
            max_tokens=self._chat.max_context_tokens,
        )
        record.context_count = len(context)
        record.would_abstain = not context
        if expected:
            ranked = [SourceRef(c.source_id, c.canonical_url) for c in record.chunks]
            record.hit_at_5 = hit_at(ranked, expected, 5)
            record.hit_at_10 = hit_at(ranked, expected, 10)
        return RetrievalOutput(record, {c.chunk_id: c.text for c in chunks})
