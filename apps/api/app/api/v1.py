"""/api/v1 routes (P0-15). Every route is behind authentication (``app.auth.middleware``:
the Phase 0 bearer token or Authentik OIDC, P1a-02).

Tenant and user come from ``request.state`` (set by authentication); every query
runs in a transaction scoped to the tenant for row-level security, and is further
restricted to the current user's own conversations.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_tenant_id, current_user_id, db_session
from app.api.schemas import (
    AskIn,
    ChatStreamEvents,
    CitationOut,
    ConversationCreated,
    ConversationDetail,
    ConversationSummary,
    FeedbackIn,
    FeedbackOut,
    Health,
    MeOut,
    MessageOut,
    SourceOut,
)
from app.audit.writer import record
from app.chat.models import Citation, Conversation, Feedback, Message
from app.chat.orchestrator import (
    ChatContext,
    ChatEvent,
    CitationsEvent,
    ConversationNotFound,
    DoneEvent,
    ErrorEvent,
    Orchestrator,
    TokenEvent,
)
from app.chat.package import tenant_package_tags
from app.content.models import Source
from app.tenancy.models import Tenant, User

router = APIRouter(prefix="/api/v1")

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")


class EventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


SSE_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


def get_orchestrator(request: Request) -> Orchestrator:
    orchestrator: Orchestrator | None = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        # No retriever wired (the RAGFlow client is configured at startup).
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="retrieval_unavailable")
    return orchestrator


def _live_conversation(user_id: UUID) -> Any:
    return (Conversation.user_id == user_id) & (Conversation.expires_at > func.now())


@router.get("/healthz", response_model=Health)
async def healthz() -> Health:
    return Health(status="ok")


@router.get("/me", response_model=MeOut)
async def me(request: Request, session: AsyncSession = Depends(db_session)) -> MeOut:
    """The signed-in user, from the request context (P1a-02)."""
    row = (
        await session.execute(
            select(User.email, User.display_name, User.role, Tenant.display_name.label("tenant"))
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(User.id == current_user_id(request))
        )
    ).one()
    return MeOut(
        email=row.email,
        display_name=row.display_name,
        role="tenant_admin" if row.role == "tenant_admin" else "user",
        tenant_display_name=row.tenant,
    )


@router.post(
    "/conversations", status_code=status.HTTP_201_CREATED, response_model=ConversationCreated
)
async def create_conversation(
    request: Request, session: AsyncSession = Depends(db_session)
) -> Conversation:
    conversation = Conversation(
        tenant_id=current_tenant_id(request), user_id=current_user_id(request)
    )
    session.add(conversation)
    await session.flush()
    await session.refresh(conversation)
    return conversation


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    request: Request, session: AsyncSession = Depends(db_session)
) -> list[Conversation]:
    rows = await session.scalars(
        select(Conversation)
        .where(_live_conversation(current_user_id(request)))
        .order_by(Conversation.updated_at.desc())
    )
    return list(rows)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID, request: Request, session: AsyncSession = Depends(db_session)
) -> ConversationDetail:
    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, _live_conversation(current_user_id(request))
        )
    )
    if conversation is None:
        raise NOT_FOUND
    messages = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.role.desc())
        )
    ).all()
    cited = await session.execute(
        select(Citation, Source)
        .join(Source, Source.id == Citation.source_id)
        .where(Citation.message_id.in_([m.id for m in messages]))
        .order_by(Citation.marker)
    )
    by_message: dict[UUID, list[CitationOut]] = {}
    for citation, source in cited:
        by_message.setdefault(citation.message_id, []).append(
            CitationOut(
                marker=citation.marker,
                source_id=source.id,
                chunk_id=citation.ragflow_chunk_id,
                page_or_slide=citation.page_or_slide,
                excerpt=citation.excerpt,
                publisher=source.publisher,
                title=source.title,
                published_on=source.published_on,
                canonical_url=source.canonical_url,
                type=source.type,
            )
        )
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        expires_at=conversation.expires_at,
        messages=[
            MessageOut(
                id=m.id,
                role="assistant" if m.role == "assistant" else "user",
                content=m.content,
                mode=m.mode,
                created_at=m.created_at,
                unsupported=m.outcome == "unsupported",
                abstained=m.outcome == "abstained",
                citations=by_message.get(m.id, []),
            )
            for m in messages
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID, request: Request, session: AsyncSession = Depends(db_session)
) -> Response:
    """Hard delete: messages, citations and feedback go with it (ON DELETE CASCADE)."""
    deleted = await session.scalar(
        delete(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user_id(request),
        )
        .returning(Conversation.id)
    )
    if deleted is None:
        raise NOT_FOUND
    await record(
        session,
        tenant_id=current_tenant_id(request),
        actor_user_id=current_user_id(request),
        event="conversation.deleted",
        metadata={"conversation_id": str(conversation_id)},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _sse(name: str, data: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n".encode()


def _frame(event: ChatEvent) -> bytes:
    if isinstance(event, TokenEvent):
        return _sse("token", {"text": event.text})
    if isinstance(event, CitationsEvent):
        return _sse("citations", {"citations": [asdict(c) for c in event.citations]})
    if isinstance(event, DoneEvent):
        return _sse("done", asdict(event))
    if isinstance(event, ErrorEvent):
        return _sse("error", {"error_code": event.error_code})
    raise TypeError(f"unknown chat event {type(event).__name__}")


async def _stream(events: AsyncIterator[ChatEvent]) -> AsyncIterator[bytes]:
    async for event in events:
        yield _frame(event)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=EventStreamResponse,
    responses={
        200: {
            "description": (
                "Server-Sent Events: any number of `token` events, then one `citations` "
                "event, then `done`; or `error` in place of the remainder. Each frame's "
                "`data` is the JSON object named after its event in ChatStreamEvents."
            ),
            "model": ChatStreamEvents,
        },
        404: {"description": "No such conversation for this user"},
    },
)
async def ask(
    conversation_id: UUID,
    body: AskIn,
    request: Request,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> EventStreamResponse:
    ctx = ChatContext(tenant_id=current_tenant_id(request), user_id=current_user_id(request))
    try:
        events = await orchestrator.answer(ctx, conversation_id, body.question)
    except ConversationNotFound:
        raise NOT_FOUND from None
    return EventStreamResponse(_stream(events), headers=SSE_HEADERS)


@router.post("/messages/{message_id}/feedback", response_model=FeedbackOut)
async def give_feedback(
    message_id: UUID,
    body: FeedbackIn,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> FeedbackOut:
    """Thumbs up/down on an assistant message in one of the user's own conversations."""
    user_id = current_user_id(request)
    tenant_id = current_tenant_id(request)
    owned = await session.scalar(
        select(Message.id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.id == message_id, Message.role == "assistant", _live_conversation(user_id))
    )
    if owned is None:
        raise NOT_FOUND
    values = {
        "tenant_id": tenant_id,
        "message_id": message_id,
        "user_id": user_id,
        "rating": body.rating,
        "comment": body.comment,
    }
    upsert = insert(Feedback).values(**values)
    await session.execute(
        upsert.on_conflict_do_update(
            index_elements=["tenant_id", "message_id", "user_id"],
            set_={"rating": upsert.excluded.rating, "comment": upsert.excluded.comment},
        )
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=user_id,
        event="chat.feedback",
        metadata={"message_id": str(message_id), "rating": body.rating},
    )
    return FeedbackOut(message_id=message_id, rating=body.rating, comment=body.comment)


@router.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: UUID, request: Request, session: AsyncSession = Depends(db_session)
) -> SourceOut:
    """Provenance of a source in the tenant's package; any other source is not found."""
    tags = tenant_package_tags(current_tenant_id(request), request.app.state.package_tags)
    source = await session.scalar(
        select(Source).where(Source.id == source_id, Source.tags.overlap(list(tags)))
    )
    if source is None:
        raise NOT_FOUND
    return SourceOut(
        id=source.id,
        title=source.title,
        publisher=source.publisher,
        published_on=source.published_on,
        canonical_url=source.canonical_url,
        type=source.type,
        withdrawn=source.status == "withdrawn",
    )
