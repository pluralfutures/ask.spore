"""Chat orchestrator (P0-14): the Phase 0 subset of architecture §5.2.

``Orchestrator.answer(ctx, conversation_id, question)`` checks the conversation and
returns an async iterator of events. The conversation fixes the workspace, mode,
model and reasoning (P1a-04); the workspace fixes the package (P1a-05):

1. load the last N turns of the conversation (bounded by tokens);
2. rewrite a follow-up into a standalone query (skipped for a first question);
3. answer-cache lookup keyed by tenant + workspace + mode + model + reasoning +
   prompt version + normalised query + corpus version + retrieval settings;
4. retrieve from every dataset of the conversation's workspace (``top_k``, threshold);
5. abstain, without any LLM call, when nothing passes the threshold;
6. de-duplicate and cap context tokens; assemble the prompt;
7. stream the answer, dropping dangling ``[n]`` markers as it streams; in corpus-only
   mode nothing is shown until the answer cites a passage;
8. map markers to chunks; no valid citation means "unsupported", and in corpus-only
   mode the uncited text is withheld and replaced by ``WITHHELD_TEXT``;
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
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.chat.citations import MarkerFilter, strip_markers
from app.chat.context import ContextChunk, estimate_tokens, select_context
from app.chat.models import Citation, Conversation, Message
from app.chat.package import Package, Provenance, provenance_by_document, workspace_package
from app.chat.prompts import AnswerPrompt, active_prompt, render_system
from app.chat.selection import Authorization, authorize, message_choice_fields
from app.core import cache
from app.core.config import Settings
from app.core.db import tenant_session
from app.core.logging import log
from app.llm.catalogue import ModelChoice
from app.llm.factory import LLMRouter
from app.llm.mistral import LLMError, Turn, Usage
from app.retrieval.protocol import Retriever
from app.retrieval.ragflow import VECTOR_SIMILARITY_WEIGHT
from app.retrieval.types import RetrievedChunk
from app.tenancy.workspaces import NO_INSTRUCTIONS, WorkspaceInstructions, active_instructions
from app.usage.ledger import record_usage

Outcome = Literal["answered", "unsupported", "abstained"]

# User-facing text, not prompt text: shown when nothing in the package is relevant.
ABSTENTION_TEXT = "Nothing relevant was found in your research package for this question."
# Shown instead of a corpus-only answer that cites no passage (findings section 11, G6):
# the prompt asks for citations, and this check holds even when an instruction or the
# model drops them. The prompt's own decline ("The passages don't answer this.") cites
# nothing either, so the text fits both cases (findings G7).
WITHHELD_TEXT = "No answer from your sources can be shown for this question. Try rephrasing it."
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
    # The answer stopped at the output budget (finish reason "length"): shown as cut off.
    truncated: bool = False


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


@dataclass(frozen=True)
class ConversationSettings:
    """Fixed when the conversation was created (P1a-04)."""

    workspace_id: uuid.UUID
    mode: str
    model: str
    reasoning: bool

    @property
    def choice(self) -> ModelChoice:
        """The model choice the router and the entitlement check take (P1a-09)."""
        return ModelChoice(self.model, self.reasoning)


@dataclass
class _Run:
    ctx: ChatContext
    conversation_id: uuid.UUID
    question: str
    history: list[Turn]
    package: Package
    started_at: datetime
    started: float
    conversation: ConversationSettings
    instructions: WorkspaceInstructions = NO_INSTRUCTIONS
    prompt: str = ""  # template ref, e.g. corpus_only/v2
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
    ) -> None:
        self._settings = settings
        self._chat = settings.models.chat
        self._db = db_factory
        self._retriever = retriever
        self._llm = llm

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
            conversation=ConversationSettings(uuid.UUID(int=0), "corpus_only", "", False),
        )
        async with tenant_session(self._db, ctx.tenant_id) as session:
            found = (
                await session.execute(
                    select(
                        Conversation.workspace_id,
                        Conversation.mode,
                        Conversation.model,
                        Conversation.reasoning,
                    ).where(
                        Conversation.id == conversation_id,
                        Conversation.user_id == ctx.user_id,
                        Conversation.expires_at > func.now(),
                    )
                )
            ).one_or_none()
            if found is None:
                raise ConversationNotFound(str(conversation_id))
            run.conversation = ConversationSettings(
                workspace_id=found.workspace_id,
                mode=found.mode,
                model=found.model,
                reasoning=found.reasoning,
            )
            run.history = await self._history(session, conversation_id)
            run.instructions = await active_instructions(session, found.workspace_id)
            # The conversation's workspace, fixed at creation, decides the datasets
            # (architecture §8 package enforcement, per workspace).
            run.package = await workspace_package(session, found.workspace_id)
            # P1a-09, P1a-10: the conversation's model checked against the entitlement
            # and the spend cap, before any outbound call.
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
            if outcome in ("abstained", "unsupported"):
                continue  # canned text, not model output (an uncited reply is withheld)
            text = strip_markers(content) if role == "assistant" else content
            budget -= estimate_tokens(text)
            if budget < 0:
                break
            turns.append(Turn(role="assistant" if role == "assistant" else "user", content=text))
        turns.reverse()
        return turns

    def _cache_key(self, run: _Run, prompt_ref: str) -> str:
        """Tenant-prefixed by ``app.core.cache``; everything that shapes the answer here.

        The retrieval settings are part of it (findings D7), so a threshold, ``top_k``,
        context cap or vector weight change never serves answers retrieved under the
        old settings. ``prompt_ref`` names the template version and the workspace's
        instructions version, so either change misses.
        """
        conversation = run.conversation
        material = "\x00".join(
            [
                str(conversation.workspace_id),
                conversation.mode,
                conversation.model,  # the model that answers (P1a-09 routes by it)
                "reasoning" if conversation.reasoning else "no-reasoning",
                prompt_ref,
                normalise_query(run.query),
                ",".join(run.package.dataset_ids),
                run.package.corpus_version,
                f"top_k={self._chat.top_k}",
                f"threshold={self._chat.similarity_threshold!r}",
                f"max_context={self._chat.max_context_tokens}",
                f"vector_weight={VECTOR_SIMILARITY_WEIGHT!r}",
            ]
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return f"answer:{conversation.mode}:{digest}"

    async def _run(self, run: _Run) -> AsyncIterator[ChatEvent]:
        # P1a-06: the mode's prompt with the workspace's tenant-authored block in its slot.
        general = run.conversation.mode == "general_knowledge"
        name: AnswerPrompt = "general_knowledge" if general else "corpus_only"
        template = active_prompt(self._settings, name)
        system = render_system(template, run.instructions.text)
        run.prompt = template.ref

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

        # Corpus-only abstains without a package; general knowledge answers without one.
        if not run.package.dataset_ids and not general:
            async for event in self._abstain(run):
                yield event
            return

        # 3. Answer cache.
        key = self._cache_key(run, f"{template.ref}+instructions/{run.instructions.version}")
        cached = await self._cache_get(run.ctx.tenant_id, key)
        if cached is not None and cached["outcome"] == "unsupported" and not general:
            cached = None  # cached before uncited replies were withheld: answer afresh
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
        chunks: list[RetrievedChunk] = []
        try:
            if run.package.dataset_ids:
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
        provenance: dict[str, Provenance] = {}
        if chunks:
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

        # 5. Abstain without an LLM call when nothing relevant remains (corpus-only).
        if not context and not general:
            async for event in self._abstain(run):
                yield event
            return

        # 7. Generation, streamed through the marker filter. In corpus-only mode the text
        # is held back until it cites a passage, so an uncited reply is never shown.
        markers = MarkerFilter(len(context))
        parts: list[str] = []
        held = not general
        try:
            stream = await self._llm.answer(
                system,
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
                    if held and markers.cited:
                        held = False
                        out = "".join(parts)  # everything held so far, in one event
                    if not held:
                        yield TokenEvent(out)
            tail = markers.flush()
            if tail:
                parts.append(tail)
                if not held:
                    yield TokenEvent(tail)
            run.add_usage(stream.usage, stream.model)
        except LLMError as exc:
            async for event in self._fail(run, exc.error_code):
                yield event
            return

        # 8. Citation mapping.
        answer = "".join(parts)
        truncated = stream.finish_reason == "length"
        if truncated and not answer.strip():
            # The whole budget went to hidden reasoning: no answer, not an unsupported one.
            # The tokens were still spent, so they count towards usage and the spend cap.
            async with tenant_session(self._db, run.ctx.tenant_id) as session:
                await record_usage(
                    session, self._settings, run.ctx.tenant_id, run.usage, run.auth.entitlement
                )
            async for event in self._fail(run, "answer_cut_off"):
                yield event
            return
        citations = [_citation(n, context[n - 1]) for n in markers.cited]
        # An uncited general-knowledge answer is expected, not unsupported (architecture §5.1).
        outcome: Outcome = "answered" if citations or general else "unsupported"
        withheld = outcome == "unsupported"
        if withheld:
            answer = WITHHELD_TEXT  # the uncited reply is neither shown nor stored
            yield TokenEvent(answer)
        yield CitationsEvent(citations)

        # 9. Cache, then persist and audit (cached first: the client may leave after done).
        # A cut-off or withheld answer is not cached, so asking again gets a fresh one.
        if not truncated and not withheld:
            await self._cache_set(
                run.ctx.tenant_id,
                key,
                {
                    "answer": answer,
                    "outcome": outcome,
                    "model": run.model,
                    "citations": [asdict(c) for c in citations],
                    # P1b-03: the register sources this answer cites, so withdrawing or
                    # re-ingesting one purges it (app.content.withdraw).
                    "source_ids": sorted({c.source_id for c in citations}),
                },
            )
        async for event in self._finish(
            run, answer, citations, outcome, truncated=truncated, withheld=withheld
        ):
            yield event

    async def _abstain(self, run: _Run) -> AsyncIterator[ChatEvent]:
        yield TokenEvent(ABSTENTION_TEXT)
        yield CitationsEvent([])
        async for event in self._finish(run, ABSTENTION_TEXT, [], "abstained"):
            yield event

    async def _finish(
        self,
        run: _Run,
        answer: str,
        citations: Sequence[CitationOut],
        outcome: Outcome,
        *,
        truncated: bool = False,
        withheld: bool = False,
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
        except SQLAlchemyError:
            # Any other database failure: an error code only. The exception's message can
            # quote the answer or question, so it is neither logged nor raised (§12).
            async for event in self._fail(run, "database_error", audit=False):
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
            error_code=(
                "answer_withheld" if withheld else "answer_truncated" if truncated else None
            ),
        )
        yield DoneEvent(
            message_id=message_id,
            unsupported=outcome == "unsupported",
            abstained=outcome == "abstained",
            cached=run.cache_hit,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            model=run.model or run.conversation.model,
            reasoning=run.conversation.reasoning,
            truncated=truncated,
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
                mode=run.conversation.mode,
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
                mode=run.conversation.mode,
                model=run.model,
                tokens_in=run.tokens_in,
                tokens_out=run.tokens_out,
                latency_ms=latency,
                outcome=outcome,
                created_at=datetime.now(UTC),
                **message_choice_fields(run.conversation.choice),
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
            "workspace_id": str(run.conversation.workspace_id),
            "mode": run.conversation.mode,
            "reasoning": run.conversation.reasoning,
            "outcome": outcome,
            "status": status,
            "error_code": error_code,
            # The model that answered, or the conversation's model when none was called.
            "model": run.model or run.conversation.model,
            "prompt": run.prompt,
            "instructions_version": run.instructions.version,
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
