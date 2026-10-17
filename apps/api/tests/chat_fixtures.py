"""Fixtures shared by the orchestrator and API tests (registered in conftest.py).

A migrated database seeded with the Phase 0 datasets and two synthetic sources, a
fake cache, application-role engine and repository settings.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.chat.orchestrator import ChatContext
from app.core import cache
from app.core.config import DEFAULT_CONFIG_DIR, Settings, load_settings
from app.retrieval.types import RetrievedChunk
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.conftest import MigratedDatabase
from tests.fakes import FakeRedis
from tests.test_config import ENV

TAGS = ("sample-analysis", "sample-reports", "sample-web")
DATASETS = {"sample-reports": "ds-reports-0001", "sample-analysis": "ds-analysis-0001"}
USAGE = {"prompt_tokens": 900, "completion_tokens": 40}


@pytest.fixture(scope="module")
def settings() -> Settings:
    return load_settings(environ=ENV, config_dir=DEFAULT_CONFIG_DIR)


@pytest.fixture
async def engine(database: MigratedDatabase) -> AsyncIterator[AsyncEngine]:
    # The application role, so RLS and grants apply as in production.
    engine = create_async_engine(
        database.sqlalchemy_url, connect_args={"server_settings": {"role": "askspore_app"}}
    )
    yield engine
    await engine.dispose()


@pytest.fixture
def redis() -> Iterator[FakeRedis]:
    fake = FakeRedis()
    cache.configure(fake)
    yield fake
    cache.configure(None)


@dataclass
class World:
    user_id: uuid.UUID
    user_email: str
    conversation_id: uuid.UUID
    sources: dict[str, uuid.UUID]  # document_id -> source_id
    admin: asyncpg.Connection

    @property
    def ctx(self) -> ChatContext:
        return ChatContext(tenant_id=INTERNAL_TENANT_ID, user_id=self.user_id)

    async def new_conversation(self, *, expired: bool = False) -> uuid.UUID:
        created = datetime.now(UTC) - (timedelta(days=31) if expired else timedelta())
        cid: uuid.UUID = await self.admin.fetchval(
            "INSERT INTO conversations (tenant_id, user_id, created_at, expires_at) "
            "VALUES ($1, $2, $3::timestamptz, $3::timestamptz + interval '30 days') RETURNING id",
            INTERNAL_TENANT_ID,
            self.user_id,
            created,
        )
        return cid


@pytest.fixture
async def world(admin_conn: asyncpg.Connection) -> World:
    for tag, dataset_id in DATASETS.items():
        await admin_conn.execute(
            "INSERT INTO datasets (tag, ragflow_dataset_id) VALUES ($1, $2) "
            "ON CONFLICT (tag) DO NOTHING",
            tag,
            dataset_id,
        )
    sources: dict[str, uuid.UUID] = {}
    specs = [
        ("pdf", "Synthetic Institute", "Synthetic Outlook 2026", "sample-reports", True),
        ("pptx", "Our Analysis Team", "Synthetic Market Deck", "sample-analysis", False),
    ]
    for kind, publisher, title, tag, as_object in specs:
        doc = f"doc-{uuid.uuid4().hex[:12]}"
        mapping = {DATASETS[tag]: doc} if as_object else [doc]
        sources[doc] = await admin_conn.fetchval(
            "INSERT INTO sources (type, title, publisher, published_on, canonical_url, "
            "licence_basis, tags, status, ragflow_document_ids) "
            "VALUES ($1, $2, $3, '2026-03-01', 'https://example.org/report', 'synthetic', "
            "ARRAY[$4], 'ingested', $5::jsonb) RETURNING id",
            kind,
            title,
            publisher,
            tag,
            json.dumps(mapping),
        )
    email = "analyst@example.org"
    user_id = await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", email)
    w = World(user_id, email, uuid.uuid4(), sources, admin_conn)
    w.conversation_id = await w.new_conversation()
    return w


def chunks_for(world: World, score: float = 0.8) -> list[RetrievedChunk]:
    (doc_a, doc_b) = list(world.sources)
    return [
        RetrievedChunk(
            chunk_id=f"chunk-{uuid.uuid4().hex[:10]}",
            document_id=doc_a,
            dataset_id=DATASETS["sample-reports"],
            text="Synthetic capacity grew by 12 percent in 2025.",
            score=score,
            page_or_slide=4,
        ),
        RetrievedChunk(
            chunk_id=f"chunk-{uuid.uuid4().hex[:10]}",
            document_id=doc_b,
            dataset_id=DATASETS["sample-analysis"],
            text="Our synthetic deck expects a slowdown in 2026.",
            score=score - 0.1,
            page_or_slide=2,
        ),
    ]
