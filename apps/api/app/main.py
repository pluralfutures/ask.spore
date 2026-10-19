"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.auth import router as api_auth
from app.api.operator import router as api_operator
from app.api.v1 import router as api_v1
from app.auth.authentik import oidc_services
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
    app.include_router(api_auth)
    app.include_router(api_v1)
    app.include_router(api_operator)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        # Unauthenticated liveness probe for Compose; carries no data.
        return {"status": "ok"}

    return app


app = create_app(retriever=RagflowRetriever())
