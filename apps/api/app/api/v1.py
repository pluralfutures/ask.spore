"""/api/v1 routes (P0-15). Every route is behind authentication (``app.auth.middleware``:
the Phase 0 bearer token or Authentik OIDC, P1a-02).

Tenant and user come from ``request.state`` (set by authentication); every query
runs in a transaction scoped to the tenant for row-level security, and is further
restricted to the current user's own conversations.

Write handlers commit before they return (C5): the ``db_session`` dependency's own
commit runs when the dependency exits, which can be after the response is sent, so a
fast client could act on a row that is not committed yet. ``app.tenant_id`` is
transaction-scoped, so nothing tenant-scoped may run on the session after the commit;
handlers build the response first, then commit, then return it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_tenant_id, current_user_id, db_session, require_tenant_admin
from app.api.schemas import (
    AskIn,
    ChatStreamEvents,
    CitationOut,
    ConversationCreated,
    ConversationCreateIn,
    ConversationDetail,
    ConversationSummary,
    FeedbackIn,
    FeedbackOut,
    Health,
    MeOut,
    MessageOut,
    ModelOptionOut,
    SourceOut,
    WorkspaceOut,
    WorkspacePromptIn,
    WorkspacePromptOut,
)
from app.audit.writer import AuditValue, record
from app.auth.middleware import IDENTITY_KEY
from app.auth.tokens import Identity
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
from app.chat.selection import choose_for_new_conversation, load_entitlement
from app.content.models import Source
from app.core.logging import log
from app.llm import catalogue
from app.mail.queue import enqueue_operator_notice
from app.operator.models import OperatorNotice
from app.tenancy.entitlements import ModelRefused, eu_fallback_choice, usable_models
from app.tenancy.models import Tenant, TenantEntitlements, User
from app.tenancy.name_flags import match_kinds, tenant_terms
from app.tenancy.retention import expiry, retention_days
from app.tenancy.workspaces import (
    ChoiceRefused,
    Workspace,
    WorkspacePrompt,
    choose,
    tenant_tags,
)

router = APIRouter(prefix="/api/v1")

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
NAME_MATCH_NOTICE = "workspace_prompt.tenant_name_match"


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
    identity = getattr(request.state, IDENTITY_KEY, None)
    return MeOut(
        email=row.email,
        display_name=row.display_name,
        role="tenant_admin" if row.role == "tenant_admin" else "user",
        tenant_display_name=row.tenant,
        # P1b-08: when the access token expires; the web app renews the session before.
        session_expires_at=identity.expires_at if isinstance(identity, Identity) else None,
    )


@router.get("/models", response_model=list[ModelOptionOut])
async def list_models(
    request: Request, session: AsyncSession = Depends(db_session)
) -> list[ModelOptionOut]:
    """The models the tenant's users may pick (P1a-09): enabled for the tenant, and
    external ones only with the external-models entitlement. ``default`` marks the
    tenant-wide EU fallback; the start panel pre-fills from the workspace's defaults
    (``GET /workspaces``)."""
    settings = request.app.state.settings
    ent = await load_entitlement(session, current_tenant_id(request))
    default = eu_fallback_choice(settings, ent)
    return [
        ModelOptionOut(
            id=e.id,
            display_name=e.display_name,
            external=e.external,
            reasoning_switch=e.can_reason,
            default=default is not None and e.id == default.model,
        )
        for e in usable_models(settings, ent)
    ]


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(session: AsyncSession = Depends(db_session)) -> list[Workspace]:
    """The tenant's workspaces (RLS), for the start panel. No tags or dataset IDs."""
    rows = await session.scalars(select(Workspace).order_by(Workspace.name, Workspace.slug))
    return list(rows)


@router.post(
    "/conversations", status_code=status.HTTP_201_CREATED, response_model=ConversationCreated
)
async def create_conversation(
    request: Request,
    body: ConversationCreateIn | None = None,
    session: AsyncSession = Depends(db_session),
) -> ConversationCreated:
    """Start a conversation in a workspace with a mode, model and reasoning, all fixed.

    Defaults come from the workspace; the mode is checked against the tenant's
    ``answer_modes``, the model and reasoning by ``choose_for_new_conversation``
    (catalogue, ``enabled_models``, external-models entitlement, reasoning switch and
    the external spend cap, P1a-09 to P1a-11). At the cap an external model falls back
    to the workspace default and the response carries the notice.
    """
    choice = body or ConversationCreateIn()
    tenant_id, user_id = current_tenant_id(request), current_user_id(request)
    entitlements = await session.get(TenantEntitlements, tenant_id)
    if entitlements is None:
        raise NOT_FOUND
    try:
        chosen = await choose(
            session,
            workspace_id=choice.workspace_id,
            mode=choice.mode,
            answer_modes=entitlements.answer_modes,
        )
        selection = await choose_for_new_conversation(
            session,
            request.app.state.settings,
            tenant_id,
            user_id,
            workspace_default=chosen.default,
            model=choice.model,
            reasoning=choice.reasoning,
        )
    except ChoiceRefused as exc:
        if exc.code == "unknown_workspace":
            raise NOT_FOUND from None
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.code) from None
    except ModelRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.code) from None
    conversation = Conversation(
        tenant_id=tenant_id,
        user_id=user_id,
        workspace_id=chosen.workspace_id,
        mode=chosen.mode,
        model=selection.choice.model,
        reasoning=selection.choice.reasoning,
        # The tenant's retention, 30 days at most (P1a-13).
        expires_at=expiry(await retention_days(session)),
    )
    session.add(conversation)
    await session.flush()
    await session.refresh(conversation)
    created = ConversationCreated.model_validate(conversation).model_copy(
        update={"notice": selection.notice, "notice_text": selection.notice_text}
    )
    await session.commit()
    return created


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
                superseded=citation.superseded_at is not None,
                withdrawn=citation.withdrawn_at is not None,
            )
        )
    workspace_name = await session.scalar(
        select(Workspace.name).where(Workspace.id == conversation.workspace_id)
    )
    listed = catalogue.entry(request.app.state.settings, conversation.model)
    return ConversationDetail(
        id=conversation.id,
        workspace_name=workspace_name or "",
        model_display_name=listed.display_name if listed else conversation.model,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        expires_at=conversation.expires_at,
        workspace_id=conversation.workspace_id,
        mode=conversation.mode,
        model=conversation.model,
        reasoning=conversation.reasoning,
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
                model=m.model if m.role == "assistant" else None,
                reasoning=m.reasoning if m.role == "assistant" else None,
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
    await session.commit()
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
    try:
        async for event in events:
            yield _frame(event)
    except SQLAlchemyError as exc:
        # A database failure mid-stream ends it with an error code; the exception's
        # message can quote the question, so only its class name is logged (§12).
        log(
            "chat.stream_failed",
            level="error",
            exception=type(exc).__name__,
            error_code="database_error",
        )
        yield _frame(ErrorEvent("database_error"))


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
    # No request-scoped session: the orchestrator commits the persisted message in its
    # own tenant transaction before it yields ``done`` (C5).
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
    out = FeedbackOut(message_id=message_id, rating=body.rating, comment=body.comment)
    await session.commit()
    return out


@router.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: UUID, request: Request, session: AsyncSession = Depends(db_session)
) -> SourceOut:
    """Provenance of a source in the tenant's package (the union of its workspaces'
    tags); any other source is not found."""
    tags = await tenant_tags(session)
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


@router.get(
    "/workspaces/{workspace_id}/prompts",
    response_model=list[WorkspacePromptOut],
    dependencies=[Depends(require_tenant_admin)],
)
async def list_workspace_prompts(
    workspace_id: UUID, request: Request, session: AsyncSession = Depends(db_session)
) -> list[WorkspacePrompt]:
    """Tenant admins: every saved version of the additional instructions, newest first."""
    if await session.scalar(select(Workspace.id).where(Workspace.id == workspace_id)) is None:
        raise NOT_FOUND
    rows = await session.scalars(
        select(WorkspacePrompt)
        .where(WorkspacePrompt.workspace_id == workspace_id)
        .order_by(WorkspacePrompt.version.desc())
    )
    return list(rows)


async def _flag_tenant_names(
    session: AsyncSession, tenant_id: UUID, prompt: WorkspacePrompt
) -> None:
    """P1a-07: a prompt naming the tenant or its people is permitted but flagged.

    Writes an operator notice and an audit event naming only the kinds that matched,
    in the save's transaction. The save succeeds either way and its response is the
    same: nothing here reaches the tenant user.
    """
    kinds = match_kinds(prompt.text, await tenant_terms(session))
    if not kinds:
        return
    metadata: dict[str, AuditValue] = {
        "workspace_id": str(prompt.workspace_id),
        "version": prompt.version,
        "match_kinds": kinds,
    }
    # No RETURNING (the ID is ours): the application role may add notices, not read them.
    notice_id = uuid4()
    await session.execute(
        insert(OperatorNotice).values(
            id=notice_id, tenant_id=tenant_id, kind=NAME_MATCH_NOTICE, metadata_=metadata
        )
    )
    # P1b-11: emailed to every operator by the worker, naming no tenant.
    await enqueue_operator_notice(session, template="tenant_name_flag", notice_id=notice_id)
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=prompt.author_user_id,
        event="workspace.prompt_tenant_name_match",
        metadata=metadata,
    )
    log("workspace.prompt_tenant_name_match", tenant_id=str(tenant_id), count=len(kinds))


@router.put(
    "/workspaces/{workspace_id}/prompt",
    response_model=WorkspacePromptOut,
    dependencies=[Depends(require_tenant_admin)],
)
async def save_workspace_prompt(
    workspace_id: UUID,
    body: WorkspacePromptIn,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> WorkspacePromptOut:
    """Tenant admins: save a new version of the additional instructions (P1a-04)."""
    tenant_id = current_tenant_id(request)
    if await session.scalar(select(Workspace.id).where(Workspace.id == workspace_id)) is None:
        raise NOT_FOUND
    latest = await session.scalar(
        select(func.max(WorkspacePrompt.version)).where(
            WorkspacePrompt.workspace_id == workspace_id
        )
    )
    prompt = WorkspacePrompt(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        version=(latest or 0) + 1,
        text=body.text.strip(),
        author_user_id=current_user_id(request),
    )
    session.add(prompt)
    try:
        await session.flush()
    except IntegrityError:
        # A concurrent save took this version number (unique per workspace).
        raise HTTPException(status.HTTP_409_CONFLICT, detail="concurrent_save") from None
    await session.refresh(prompt)
    await record(
        session,
        tenant_id=tenant_id,
        actor_user_id=current_user_id(request),
        event="workspace.prompt_saved",
        metadata={"workspace_id": str(workspace_id), "version": prompt.version},
    )
    log("workspace.prompt_saved", tenant_id=str(tenant_id), user_id=str(prompt.author_user_id))
    await _flag_tenant_names(session, tenant_id, prompt)
    out = WorkspacePromptOut.model_validate(prompt)
    await session.commit()
    return out
