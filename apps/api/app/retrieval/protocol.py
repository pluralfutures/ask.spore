"""The retrieval interface the chat orchestrator depends on.

Implemented by the RAGFlow client (app.retrieval.ragflow, P0-07) and by the fake
in tests/fakes.py. Dataset IDs are always resolved server-side from the tenant's
package (app.chat.package); no caller passes IDs taken from a request.
"""

from __future__ import annotations

from typing import Protocol

from app.retrieval.types import RetrievedChunk


class Retriever(Protocol):
    async def retrieve(
        self, *, dataset_ids: list[str], query: str, top_k: int, similarity_threshold: float
    ) -> list[RetrievedChunk]: ...
