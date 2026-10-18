# Stack Decision Record

Oct 17, 2026 · Status: accepted

Fixes the technology choices left open in the Platform Architecture & Functional Design so that implementation does not re-decide them. Change this file first if a choice changes.

## Decisions

| Area | Choice | Pinned version policy | Why |
| --- | --- | --- | --- |
| Repository | Single monorepo `ask.spore` | n/a | One design, one CI, one deploy unit at this scale |
| API and workers | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2 | Pin minor versions in `pyproject.toml`; `uv` for dependency management | RAGFlow SDK, Mistral SDK and document tooling are Python-first |
| Web app | React 18, TypeScript, Vite, TanStack Query, Tailwind CSS | Pin in `package.json`; `pnpm` | Common, well-understood by coding models, small bundle |
| App database | PostgreSQL 16 | Major pinned in Compose | Row-level security, JSONB for citation sets |
| Cache, sessions, rate limits | Redis 7 | Major pinned | Simple; already part of the RAGFlow stack skill set |
| Retrieval | RAGFlow, official Docker Compose, Elasticsearch backend, bundled embedding model | Pin RAGFlow image tag; record it in `infra/ragflow/VERSION` | Per the architecture document |
| RAGFlow client | Raw HTTP (`httpx`, async) for every call. Originally "`ragflow-sdk` where it covers the call"; changed in P0-07 because the SDK is synchronous `requests` without timeouts and lags the server API (findings R10) | Contract tests against responses recorded from the pinned RAGFlow version; re-record on upgrade | Async, bounded timeouts, no drift hidden inside an SDK |
| LLM (target) | `mistralai` Python SDK against the EU endpoint; model `mistral-large-*` dated version in config, never `-latest` in production | Pin model string in `config/models.toml` | Reproducible evals |
| LLM (Phase 0, active) | Scaleway Generative APIs (Paris) via OpenAI-compatible client (`openai` SDK with custom base URL), model `deepseek-v4.1-flash` for chat, rewrite and judge | Pin the served model name; Scaleway names are not dated, so the startup check accepts them when they contain no `latest` | Decided Oct 18, 2026: the Mistral workspace had no API quota and no Large tier during Phase 0; Scaleway was already the designated second provider. Mistral code and config stay in place, inactive, behind a `[llm] provider` switch |
| Fallback LLM | Whichever of the two providers is not active | Pin model string | Second EU provider |
| External models (Phase 1a) | OpenRouter via the same OpenAI-compatible client with zero-data-retention routing set on every request; models `openai/gpt-6.1-sol`, `anthropic/claude-opus-5.5` | Pin model slugs; ZDR flag asserted by a test | Owner decision Oct 18, 2026 (architecture §14, compliance addendum); non-EU, per-tenant opt-in |
| Identity (Phase 1+) | Authentik, official Compose | Pin image tag | Per the architecture document; not used in Phase 0 |
| Email (Phase 1+) | Scaleway Transactional Email over SMTP | n/a | Sign-in links |
| Reverse proxy | Caddy | Pin image tag | Automatic TLS, minimal config |
| Containers | Docker Compose, one file per environment under `infra/` | Compose v2 | Matches RAGFlow's own distribution |
| Observability | Structured JSON logs to stdout; Prometheus metrics endpoint; Grafana + Loki in `infra/monitoring` (Phase 1+) | n/a | Stays on the VPS |
| Testing | `pytest` + `pytest-asyncio` + `httpx` test client; `vitest` + Playwright for web | n/a | Standard |
| Lint and format | `ruff` (lint + format), `mypy --strict` on `app/`, `eslint` + `prettier` | n/a | Custom ruff rules enforce the logging and cache controls |
| CI | GitHub Actions: lint, typecheck, unit tests, integration tests against Compose services, eval gate | n/a | Branch protection on `main` |
| Secrets | `.env` files locally (git-ignored); Scaleway Secret Manager in staging/production, injected as environment variables at deploy | n/a | Per the architecture document |

## Repository layout

```
ask.spore/
  CLAUDE.md                  rules for coding sessions
  README.md
  design/                    design documents and phase specs
  apps/
    api/                     FastAPI service and workers
      app/
        core/                config, logging, security helpers
        tenancy/             tenants, packages (Phase 1)
        chat/                orchestration, prompts, citations
        retrieval/           RAGFlow client
        llm/                 Mistral and Scaleway clients
        content/             source register, ingestion, crawler
        audit/
        api/                 routers
      alembic/
      tests/
      pyproject.toml
    web/                     React app
  packages/
    eval/                    eval set and harness
  infra/
    compose.dev.yml
    compose.staging.yml
    compose.prod.yml
    ragflow/                 pinned RAGFlow compose and .env template
    caddy/
    monitoring/
  config/
    models.toml              provider endpoints and pinned model names
    prompts/                 versioned prompt templates
  .github/workflows/
```

## Conventions

- Every tenant-scoped table has a `tenant_id` column, a row-level-security policy, and an index starting with `tenant_id`. The API sets `app.tenant_id` on the connection per request; no query bypasses it. In Phase 0 there is one implicit tenant, but the column and policy exist from the first migration.
- Logging goes through `app.core.logging.log()` which accepts only allow-listed fields. Logging `message`, `answer`, `query`, `prompt`, `chunk_text` or any request body is forbidden and is caught by a custom ruff rule and a code-review checklist item.
- Cache access goes through `app.core.cache` helpers that require a tenant ID argument. Direct Redis calls outside that module are forbidden.
- Prompts are files under `config/prompts/<mode>/<version>.md`; the active version is set in `config/models.toml`. Prompt text is never built with string concatenation in code.
- All outbound hosts (Mistral, Scaleway, OpenRouter, RAGFlow, SMTP) are listed in `config/models.toml` and checked at startup against the allow-list, which is split into EU hosts and external hosts; the API refuses to start otherwise, and refuses an external host for a tenant without the "external models" entitlement.
- Migrations only through Alembic; schema changes never by hand.
