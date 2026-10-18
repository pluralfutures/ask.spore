"""P0-07: the RAGFlow client against the Compose RAGFlow (marked ``integration``).

Not run in unit CI. Needs the dev stack (infra/compose.dev.yml) and:

- RAGFLOW_TEST_BASE_URL: RAGFlow as reachable from where the tests run, e.g.
  ``http://127.0.0.1:8080`` (the loopback UI port, whose nginx proxies the API) on
  the host, or ``http://ragflow:9380`` inside the Compose network;
- RAGFLOW_TEST_API_KEY: an API key created in the RAGFlow UI;
- RAGFLOW_TEST_EMBEDDING_MODEL (optional, default ``BAAI/bge-m3@Builtin``).

Run with ``uv run pytest -m integration``. The test creates its own dataset from a
synthetic fixture and deletes it afterwards.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.retrieval.ragflow import RagflowClient, RagflowDataset

pytestmark = pytest.mark.integration

CORPUS = Path(__file__).resolve().parents[3] / "packages" / "eval" / "fixtures" / "corpus"
PARSE_TIMEOUT_SECONDS = 600


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} not set")
    return value


@pytest.fixture
async def client() -> AsyncIterator[RagflowClient]:
    async with RagflowClient(
        _env("RAGFLOW_TEST_BASE_URL"), _env("RAGFLOW_TEST_API_KEY"), 60
    ) as ragflow_client:
        yield ragflow_client


@pytest.fixture
async def dataset(client: RagflowClient) -> AsyncIterator[RagflowDataset]:
    created = await client.create_dataset(
        f"ask-spore-it-{uuid.uuid4().hex[:8]}",
        "naive",
        os.environ.get("RAGFLOW_TEST_EMBEDDING_MODEL", "BAAI/bge-m3@Builtin"),
    )
    try:
        yield created
    finally:
        # Test clean-up only; the client deliberately has no delete call.
        async with httpx.AsyncClient(
            base_url=os.environ["RAGFLOW_TEST_BASE_URL"].rstrip("/") + "/api/v1",
            headers={"Authorization": f"Bearer {os.environ['RAGFLOW_TEST_API_KEY']}"},
        ) as http:
            await http.request("DELETE", "/datasets", json={"ids": [created.id]})


async def test_upload_parse_and_retrieve(client: RagflowClient, dataset: RagflowDataset) -> None:
    assert dataset.id in {d.id for d in await client.list_datasets()}

    source = CORPUS / "hollin-grid-tariffs.md"
    document = await client.upload_document(dataset.id, source.name, source.read_bytes())
    await client.set_document_chunk_method(dataset.id, document.id, "naive")
    await client.start_parse(dataset.id, [document.id])

    deadline = time.monotonic() + PARSE_TIMEOUT_SECONDS
    while not (document := await client.get_document(dataset.id, document.id)).finished:
        assert time.monotonic() < deadline, "parsing did not finish in time"
        await asyncio.sleep(2)
    assert document.run == "DONE", document.progress_msg
    assert document.chunk_count > 0

    chunks = await client.retrieve_chunks(
        dataset_ids=[dataset.id],
        question="How much did household peak demand fall after the tariff change?",
        top_k=5,
        similarity_threshold=0.1,
    )
    assert chunks
    assert all(c.dataset_id == dataset.id and c.document_id == document.id for c in chunks)
    assert any("6 percent" in c.text for c in chunks)

    nothing = await client.retrieve_chunks(
        dataset_ids=[dataset.id], question="zzqx vbnm", top_k=5, similarity_threshold=0.99
    )
    assert nothing == []
