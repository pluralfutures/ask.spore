"""Switch a source's RAGFlow documents on or off together (P2A-01, P2A-03).

Used by the register's pause and resume and by ingestion, when a new version of a paused
source inherits the pause. Dataset and document IDs come from the register only.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.retrieval.ragflow import RagflowClient, RagflowError


async def set_enabled_everywhere(
    client: RagflowClient, pairs: Sequence[tuple[str, str]], *, enabled: bool
) -> tuple[str | None, bool]:
    """Switch every document; on a failure switch back the ones already done.

    Returns the failure's error code (None when all succeeded; never the exception,
    whose message names the file, P2A-13) and whether switching back failed
    too, which leaves RAGFlow disagreeing with the register (``datasets sync`` reports
    it). No partial state is ever recorded on the row.
    """
    done: list[tuple[str, str]] = []
    for dataset_id, document_id in pairs:
        try:
            await client.set_document_enabled(dataset_id, document_id, enabled=enabled)
        except RagflowError as exc:
            undo_failed = False
            for undo_dataset, undo_document in reversed(done):
                try:
                    await client.set_document_enabled(
                        undo_dataset, undo_document, enabled=not enabled
                    )
                except RagflowError:
                    undo_failed = True
            return exc.error_code, undo_failed
        done.append((dataset_id, document_id))
    return None, False
