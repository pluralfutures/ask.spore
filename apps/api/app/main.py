"""FastAPI application entry point."""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.admin import router as api_admin
from app.api.auth import router as api_auth
from app.api.content import router as api_content
from app.api.files import router as api_files
from app.api.operator import router as api_operator
from app.api.v1 import router as api_v1
from app.auth.authentik import oidc_services
from app.auth.eval_service import EvalServiceValidator
from app.auth.middleware import AuthMiddleware
from app.chat.orchestrator import Orchestrator
from app.chat.prompts import active_prompt
from app.core import cache
from app.core.config import get_settings
from app.core.db import create_engine, session_factory
from app.core.logging import log
from app.llm import catalogue
from app.llm.factory import create_llm_router
from app.retrieval.protocol import Retriever
from app.retrieval.ragflow import RagflowRetriever


class ErrorBoundary:
    """Outermost application middleware: no exception leaves the app (findings §12).

    uvicorn logs an exception that escapes the app with its traceback on stderr, and a
    database error's message can quote request text. Here every exception becomes one
    allow-listed log line (route template, method, exception class name, request ID)
    and a JSON error code: ``database_error`` for SQLAlchemy errors, else
    ``internal_error``. Nothing from the exception's message is logged or returned. If
    the response has already started (a stream), it is ended instead.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked)
        except Exception as exc:  # the boundary: reported by class name only
            error_code = "database_error" if isinstance(exc, SQLAlchemyError) else "internal_error"
            request_id = str(uuid.uuid4())
            log(
                "api.error",
                level="error",
                request_id=request_id,
                route=getattr(scope.get("route"), "path", None),
                method=scope.get("method"),
                exception=type(exc).__name__,
                status=500,
                error_code=error_code,
            )
            if started:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
            body = json.dumps({"detail": error_code, "request_id": request_id}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})


def create_app(retriever: Retriever | None = None) -> FastAPI:
    """``retriever`` is the RAGFlow retriever (P0-07). Without one, asking returns 503."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Raises ConfigError (and the server exits) if any startup check fails.
        settings = get_settings()
        app.state.settings = settings
        # P1a-10: warns per catalogue entry still marked price_placeholder (none since Oct 19).
        catalogue.warn_placeholder_prices(settings)
        engine = create_engine(settings.secrets.database_url.get_secret_value())
        app.state.db_factory = session_factory(engine)
        cache.connect(settings.secrets.redis_url.get_secret_value())
        # P1a-10: answers follow the conversation's model choice; rewrites stay default.
        llm = create_llm_router(settings, active_prompt(settings, "rewrite").text)
        auth_http = httpx.AsyncClient(timeout=10)
        if settings.models.auth.mode == "oidc":
            # P1a-02: Authentik on the Compose network; its secrets are checked at startup.
            app.state.token_validator, app.state.sign_in_provider = oidc_services(
                settings, auth_http
            )
            service = settings.models.auth.eval_service
            if service is not None:
                # P1b-15 a: the eval harness's service identity (never in production).
                app.state.eval_service = EvalServiceValidator(
                    service.public_key, service.email, service.max_lifetime_seconds
                )
                log("api.eval_service_enabled", level="warning", status="enabled")
        if retriever is not None:
            app.state.orchestrator = Orchestrator(
                settings=settings,
                db_factory=app.state.db_factory,
                retriever=retriever,
                llm=llm,
            )
        log("api.started", status="ok" if retriever is not None else "no_retriever")
        try:
            yield
        finally:
            provider = getattr(app.state, "sign_in_provider", None)
            if provider is not None:
                await provider.aclose()
            await auth_http.aclose()
            await llm.aclose()
            await cache.close()
            await engine.dispose()

    app = FastAPI(title="ask.spore API", version="0.0.0", lifespan=lifespan)
    # [auth] mode: the Phase 0 shared token (eval harness) or Authentik OIDC (P1a-02).
    app.add_middleware(AuthMiddleware)
    # Added last, so it wraps every route and the auth middleware (findings §12).
    app.add_middleware(ErrorBoundary)
    app.include_router(api_auth)
    app.include_router(api_v1)
    app.include_router(api_operator)
    app.include_router(api_admin)
    app.include_router(api_files)
    app.include_router(api_content)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        # Unauthenticated liveness probe for Compose; carries no data.
        return {"status": "ok"}

    return app


app = create_app(retriever=RagflowRetriever())
