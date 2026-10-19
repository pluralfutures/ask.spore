"""Chat orchestrator (P0-14): the Phase 0 subset of architecture §5.2, corpus-only mode.

``Orchestrator.answer(ctx, conversation_id, question)`` checks the conversation and
returns an async iterator of events:

1. load the last N turns of the conversation (bounded by tokens);
2. rewrite a follow-up into a standalone query (skipped for a first question);
3. answer-cache lookup keyed by tenant + mode + normalised query + package + corpus
   version (+ prompt version and model);
4. retrieve from every dataset of the tenant's package (``top_k``, threshold);
5. abstain, without any LLM call, when nothing passes the threshold;
6. de-duplicate and cap context tokens; assemble the prompt;
7. stream the answer, dropping dangling ``[n]`` markers as it streams;
8. map markers to chunks; no valid citation means "unsupported";
9. persist both messages, citations and usage; write an audit event; cache.

No database transaction is held open while waiting on retrieval or the model.
Nothing identifying the tenant, user, conversation or package reaches the model:
only ``PromptChunk`` and ``Turn`` values cross into ``app.llm.mistral``.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.chat.citations import MarkerFilter, strip_markers
from app.chat.context import ContextChunk, estimate_tokens, select_context
from app.chat.models import Citation, Conversation, Message
from app.chat.package import (
    Package,
    provenance_by_document,
    resolve_package,
    tenant_package_tags,
)
from app.chat.prompts import active_prompt
from app.chat.selection import Authorization, authorize, message_choice_fields
from app.core import cache
from app.core.config import Settings
from app.core.db import tenant_session
from app.core.logging import log
from app.llm.factory import LLMRouter
from app.llm.mistral import LLMError, Turn, Usage
from app.retrieval.protocol import Retriever
from app.usage.ledger import record_usage

MODE = "corpus_only"
Outcome = Literal["answered", "unsupported", "abstained"]

# User-facing text, not prompt text: shown when nothing in the package is relevant.
ABSTENTION_TEXT = "Nothing relevant was found in your research package for this question."
EXCERPT_MAX_CHARS = 1200
TITLE_MAX_CHARS = 80
_SPACE = re.compile(r"\s+")


class ConversationNotFound(LookupError):
    """No live conversation with this ID for this user (RLS also scopes to the tenant)."""


@dataclass(frozen=True)
class ChatContext:
    """Set by authentication, never from request parameters."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID


@dataclass(frozen=True)
class CitationOut:
    marker: int
    source_id: str
    chunk_id: str
    page_or_slide: int | None
    excerpt: str
    publisher: str
    title: str
    published_on: str | None
    canonical_url: str | None
    type: str


@dataclass(frozen=True)
class TokenEvent:
    text: str


@dataclass(frozen=True)
class CitationsEvent:
    citations: list[CitationOut]


@dataclass(frozen=True)
class DoneEvent:
    message_id: uuid.UUID
    unsupported: bool
    abstained: bool
    cached: bool
    tokens_in: int
    tokens_out: int
    # Badge data (P1a-11): the conversation's model and its reasoning switch.
    model: str | None = None
    reasoning: bool = False


@dataclass(frozen=True)
class ErrorEvent:
    error_code: str


ChatEvent = TokenEvent | CitationsEvent | DoneEvent | ErrorEvent


def normalise_query(query: str) -> str:
    text = unicodedata.normalize("NFKC", query).casefold()
    return _SPACE.sub(" ", text).strip().strip("?!.;: ")


def _citation(marker: int, item: ContextChunk) -> CitationOut:
    published: date | None = item.provenance.published_on
    return CitationOut(
        marker=marker,
        source_id=str(item.provenance.source_id),
        chunk_id=item.chunk.chunk_id,
        page_or_slide=item.page_or_slide,
        excerpt=item.chunk.text[:EXCERPT_MAX_CHARS],
        publisher=item.provenance.publisher,
        title=item.provenance.title,
        published_on=published.isoformat() if published else None,
        canonical_url=item.provenance.canonical_url,
        type=item.provenance.type,
    )


@dataclass
class _Run:
    ctx: ChatContext
    conversation_id: uuid.UUID
    question: str
    history: list[Turn]
    package: Package
    started_at: datetime
    started: float
    query: str = ""
    # P1a-09: the conversation's model choice, or why the tenant may not use it.
    auth: Authorization = field(default_factory=lambda: Authorization(None, None, None))
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    # P1a-10: per model, for the usage ledger (rewrite and answer may differ).
    usage: list[tuple[str, Usage]] = field(default_factory=list)
    cache_hit: bool = False
    retrieved: int = 0
    context: int = 0

    def add_usage(self, usage: Usage | None, model: str) -> None:
        if usage is not None:
            self.tokens_in += usage.tokens_in
            self.tokens_out += usage.tokens_out
            self.usage.append((model, usage))

    def latency_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)


class Orchestrator:
    def __init__(
        self,
        *,
        settings: Settings,
        db_factory: async_sessionmaker[AsyncSession],
        retriever: Retriever,
        llm: LLMRouter,
        package_tags: tuple[str, ...],
    ) -> None:
        self._settings = settings
        self._chat = settings.models.chat
        self._db = db_factory
        self._retriever = retriever
        self._llm = llm
        self._tags = package_tags

    async def answer(
        self, ctx: ChatContext, conversation_id: uuid.UUID, question: str
    ) -> AsyncIterator[ChatEvent]:
        """Check the conversation, then return the event stream for this question.

        Raises ConversationNotFound before any event when the conversation is not the
        user's, belongs to another tenant, or has expired.
        """
        run = _Run(
            ctx=ctx,
            conversation_id=conversation_id,
            question=question.strip(),
            history=[],
            package=Package((), (), ""),
            started_at=datetime.now(UTC),
            started=time.perf_counter(),
        )
        async with tenant_session(self._db, ctx.tenant_id) as session:
            found = await session.scalar(
                select(Conversation.id).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == ctx.user_id,
                    Conversation.expires_at > func.now(),
                )
            )
            if found is None:
                raise ConversationNotFound(str(conversation_id))
            run.history = await self._history(session, conversation_id)
            run.package = await resolve_package(
                session, tenant_package_tags(ctx.tenant_id, self._tags)
            )
            run.auth = await authorize(session, self._settings, ctx.tenant_id, conversation_id)
        return self._run(run)

    async def _history(self, session: AsyncSession, conversation_id: uuid.UUID) -> list[Turn]:
        if self._chat.history_messages == 0:
            return []
        rows = (
            await session.execute(
                select(Message.role, Message.content, Message.outcome)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc(), Message.role.asc())
                .limit(self._chat.history_messages)
            )
        ).all()
        turns: list[Turn] = []
        budget = self._chat.history_max_tokens
        for role, content, outcome in rows:
            if outcome == "abstained":
                continue  # canned text, not model output
            text = strip_markers(content) if role == "assistant" else content
            budget -= estimate_tokens(text)
            if budget < 0:
                break
            turns.append(Turn(role="assistant" if role == "assistant" else "user", content=text))
        turns.reverse()
        return turns

    def _cache_key(self, run: _Run, prompt_ref: str) -> str:
        material = "\x00".join(
            [
                normalise_query(run.query),
                ",".join(run.package.dataset_ids),
                run.package.corpus_version,
                prompt_ref,
                # P1a-10, P1a-11: the conversation's model choice (P1a-05 owns the key).
                f"{run.auth.choice.model}:{int(run.auth.choice.reasoning)}"
                if run.auth.choice
                else self._llm.chat_model,
            ]
        )
        return f"answer:{MODE}:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"

    async def _run(self, run: _Run) -> AsyncIterator[ChatEvent]:
        system = active_prompt(self._settings, "corpus_only")

        # 1b. Model entitlement and spend cap (P1a-09, P1a-10): before any outbound call.
        refusal = run.auth.refusal
        if refusal is None and run.auth.model and not self._llm.serves(run.auth.model):
            refusal = "model_unavailable"  # e.g. external, without OPENROUTER_API_KEY
        if refusal is not None:
            async for event in self._fail(run, refusal):
                yield event
            return

        # 2. Query rewriting, only when there is history to resolve against.
        run.query = run.question
        if run.history:
            try:
                rewritten = await self._llm.rewrite(run.question, run.history)
                run.query = rewritten.query
                run.add_usage(rewritten.usage, self._llm.rewrite_model)
            except LLMError as exc:
                # Degrade to the literal question rather than fail the turn.
                log("chat.rewrite_failed", level="warning", error_code=exc.error_code)

        if not run.package.dataset_ids:
            async for event in self._abstain(run):
                yield event
            return

        # 3. Answer cache.
        key = self._cache_key(run, system.ref)
        cached = await self._cache_get(run.ctx.tenant_id, key)
        if cached is not None:
            run.cache_hit = True
            run.model = cached["model"]
            citations = [CitationOut(**c) for c in cached["citations"]]
            yield TokenEvent(cached["answer"])
            yield CitationsEvent(citations)
            async for event in self._finish(run, cached["answer"], citations, cached["outcome"]):
                yield event
            return

        # 4. Retrieval from every dataset in the package; IDs never from the request.
        try:
            chunks = await self._retriever.retrieve(
                dataset_ids=list(run.package.dataset_ids),
                query=run.query,
                top_k=self._chat.top_k,
                similarity_threshold=self._chat.similarity_threshold,
            )
        except Exception:  # any retrieval failure is reported as one code, without detail
            async for event in self._fail(run, "retrieval_unavailable"):
                yield event
            return
        run.retrieved = len(chunks)

        # 6. Chunk selection with provenance.
        async with tenant_session(self._db, run.ctx.tenant_id) as session:
            provenance = await provenance_by_document(
                session, sorted({c.document_id for c in chunks})
            )
        context = select_context(
            chunks,
            provenance,
            dataset_ids=run.package.dataset_ids,
            similarity_threshold=self._chat.similarity_threshold,
            max_tokens=self._chat.max_context_tokens,
        )
        run.context = len(context)

        # 5. Abstain without an LLM call when nothing relevant remains.
        if not context:
            async for event in self._abstain(run):
                yield event
            return

        # 7. Generation, streamed through the marker filter.
        markers = MarkerFilter(len(context))
        parts: list[str] = []
        try:
            stream = await self._llm.answer(
                system.text,
                [c.for_prompt() for c in context],
                run.history,
                run.question,
                run.auth.choice,
            )
            run.model = stream.model
            async for delta in stream:
                out = markers.feed(delta)
                if out:
                    parts.append(out)
                    yield TokenEvent(out)
            tail = markers.flush()
            if tail:
                parts.append(tail)
                yield TokenEvent(tail)
            run.add_usage(stream.usage, stream.model)
        except LLMError as exc:
            async for event in self._fail(run, exc.error_code):
                yield event
            return

        # 8. Citation mapping.
        answer = "".join(parts)
        citations = [_citation(n, context[n - 1]) for n in markers.cited]
        outcome: Outcome = "answered" if citations else "unsupported"
        yield CitationsEvent(citations)

        # 9. Cache, then persist and audit (cached first: the client may leave after done).
        await self._cache_set(
            run.ctx.tenant_id,
            key,
            {
                "answer": answer,
                "outcome": outcome,
                "model": run.model,
                "citations": [asdict(c) for c in citations],
            },
        )
        async for event in self._finish(run, answer, citations, outcome):
            yield event

    async def _abstain(self, run: _Run) -> AsyncIterator[ChatEvent]:
        yield TokenEvent(ABSTENTION_TEXT)
        yield CitationsEvent([])
        async for event in self._finish(run, ABSTENTION_TEXT, [], "abstained"):
            yield event

    async def _finish(
        self, run: _Run, answer: str, citations: Sequence[CitationOut], outcome: Outcome
    ) -> AsyncIterator[ChatEvent]:
        message_id = uuid.uuid4()
        latency = run.latency_ms()
        try:
            # Leaving the block commits, so the message is durable before ``done`` (C5).
            async with tenant_session(self._db, run.ctx.tenant_id) as session:
                await self._persist(session, run, message_id, answer, citations, outcome, latency)
        except IntegrityError:
            # The conversation was deleted while the answer streamed.
            async for event in self._fail(run, "conversation_gone", audit=False):
                yield event
            return
        log(
            "chat.answer",
            tenant_id=str(run.ctx.tenant_id),
            user_id=str(run.ctx.user_id),
            conversation_id=str(run.conversation_id),
            message_id=str(message_id),
            latency_ms=latency,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            model=run.model,
            status=outcome,
            chunk_count=run.context,
        )
        yield DoneEvent(
            message_id=message_id,
            unsupported=outcome == "unsupported",
            abstained=outcome == "abstained",
            cached=run.cache_hit,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            model=run.model or (run.auth.choice.model if run.auth.choice else None),
            reasoning=bool(run.auth.choice and run.auth.choice.reasoning),
        )

    async def _persist(
        self,
        session: AsyncSession,
        run: _Run,
        message_id: uuid.UUID,
        answer: str,
        citations: Sequence[CitationOut],
        outcome: Outcome,
        latency: int,
    ) -> None:
        tenant_id = run.ctx.tenant_id
        session.add(
            Message(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                conversation_id=run.conversation_id,
                role="user",
                content=run.question,
                mode=MODE,
                created_at=run.started_at,
            )
        )
        session.add(
            Message(
                id=message_id,
                tenant_id=tenant_id,
                conversation_id=run.conversation_id,
                role="assistant",
                content=answer,
                mode=MODE,
                model=run.model,
                tokens_in=run.tokens_in,
                tokens_out=run.tokens_out,
                latency_ms=latency,
                outcome=outcome,
                created_at=datetime.now(UTC),
                **message_choice_fields(run.auth.choice),
            )
        )
        await session.flush()
        session.add_all(
            Citation(
                tenant_id=tenant_id,
                message_id=message_id,
                marker=c.marker,
                source_id=uuid.UUID(c.source_id),
                ragflow_chunk_id=c.chunk_id,
                page_or_slide=c.page_or_slide,
                excerpt=c.excerpt,
            )
            for c in citations
        )
        await session.execute(
            update(Conversation)
            .where(Conversation.id == run.conversation_id)
            .values(
                updated_at=func.now(),
                title=func.coalesce(Conversation.title, run.question[:TITLE_MAX_CHARS]),
            )
        )
        await record_usage(session, self._settings, tenant_id, run.usage, run.auth.entitlement)
        await record(
            session,
            tenant_id=tenant_id,
            actor_user_id=run.ctx.user_id,
            event="chat.query",
            metadata=self._audit_metadata(run, outcome, "ok", message_id, citations),
        )

    def _audit_metadata(
        self,
        run: _Run,
        outcome: str | None,
        status: str,
        message_id: uuid.UUID | None,
        citations: Sequence[CitationOut],
        error_code: str | None = None,
    ) -> dict[str, Any]:
        return {
            "conversation_id": str(run.conversation_id),
            "message_id": str(message_id) if message_id else None,
            "mode": MODE,
            "outcome": outcome,
            "status": status,
            "error_code": error_code,
            "model": run.model or (run.auth.choice.model if run.auth.choice else None),
            "reasoning": bool(run.auth.choice and run.auth.choice.reasoning),
            "prompt": active_prompt(self._settings, "corpus_only").ref,
            "cache_hit": run.cache_hit,
            "retrieved_chunk_count": run.retrieved,
            "context_chunk_count": run.context,
            "cited_chunk_ids": [c.chunk_id for c in citations],
            "cited_source_ids": sorted({c.source_id for c in citations}),
            "corpus_version": run.package.corpus_version,
            "tokens_in": run.tokens_in,
            "tokens_out": run.tokens_out,
            "latency_ms": run.latency_ms(),
        }

    async def _fail(
        self, run: _Run, error_code: str, *, audit: bool = True
    ) -> AsyncIterator[ChatEvent]:
        log(
            "chat.answer",
            level="error",
            tenant_id=str(run.ctx.tenant_id),
            user_id=str(run.ctx.user_id),
            conversation_id=str(run.conversation_id),
            latency_ms=run.latency_ms(),
            status="error",
            error_code=error_code,
        )
        if audit:
            async with tenant_session(self._db, run.ctx.tenant_id) as session:
                await record(
                    session,
                    tenant_id=run.ctx.tenant_id,
                    actor_user_id=run.ctx.user_id,
                    event="chat.query",
                    metadata=self._audit_metadata(run, None, "error", None, [], error_code),
                )
        yield ErrorEvent(error_code)

    async def _cache_get(self, tenant_id: uuid.UUID, key: str) -> dict[str, Any] | None:
        try:
            raw = await cache.get(tenant_id, key)
            value: dict[str, Any] | None = json.loads(raw) if raw else None
            return value
        except Exception:  # an unavailable or corrupt cache is a miss, never a failure
            log("chat.cache_unavailable", level="warning", error_code="cache_get")
            return None

    async def _cache_set(self, tenant_id: uuid.UUID, key: str, value: dict[str, Any]) -> None:
        try:
            await cache.set(
                tenant_id, key, json.dumps(value, ensure_ascii=False), self._chat.cache_ttl_seconds
            )
        except Exception:
            log("chat.cache_unavailable", level="warning", error_code="cache_set")
