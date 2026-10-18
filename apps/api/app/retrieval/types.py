"""Retrieval result type shared by the RAGFlow client and the chat orchestrator.

Dependency-free by contract: Group B (RAGFlow client) and Group C (orchestrator)
create this file identically.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    dataset_id: str
    text: str
    score: float
    page_or_slide: int | None
