# Stack Decision Record

Oct 17, 2026 · Status: accepted

Fixes the technology choices left open in the Platform Architecture & Functional Design so that implementation does not re-decide them. Change this file first if a choice changes.

## Decisions

| Area | Choice | Pinned version policy | Why |
| --- | --- | --- | --- |
| Repository | Single monorepo `ask.spore` | n/a | One design, one CI, one deploy unit at this scale |
| API and workers | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2 | Pin minor versions in `pyproject.toml`; `uv` for dependency management | RAGFlow SDK, Mistral SDK and document tooling are Python-first |
| Web app | React 18, TypeScript, Vite, TanStack Query, Tailwind CSS; typeface Lato (SIL OFL 1.1), vendored `woff2` files in `apps/web/src/assets/fonts/lato/` and served from our own origin (UX-05, Oct 24, 2026); icons `lucide-react` (ISC), bundled and tree-shaken (UX-06, Oct 24, 2026); Markdown in answers and the consent notice through `react-markdown` with `remark-gfm` (MIT) for tables, strikethrough, task lists and footnotes, raw HTML still off (P2B-01, Oct 27, 2026) | Pin in `package.json`; `pnpm`; Lato files from the Google Fonts build as packaged by Fontsource 5.1.0 (Latin and Latin Extended); `lucide-react` 1.53.0; `react-markdown` 10.1.0, `remark-gfm` 4.0.1 | Common, well-understood by coding models, small bundle; no font CDN (the CSP is `font-src 'self'`); icons are inline SVG in the bundle, so nothing is fetched at run time |
| App database | PostgreSQL 16 | Major pinned in Compose | Row-level security, JSONB for citation sets |
| Cache, sessions, rate limits | Redis 7 | Major pinned | Simple; already part of the RAGFlow stack skill set |
| Retrieval | RAGFlow, official Docker Compose, Elasticsearch backend, bundled embedding model | Pin RAGFlow image tag; record it in `infra/ragflow/VERSION` | Per the architecture document |
| RAGFlow client | Raw HTTP (`httpx`, async) for every call. Originally "`ragflow-sdk` where it covers the call"; changed in P0-07 because the SDK is synchronous `requests` without timeouts and lags the server API (findings R10) | Contract tests against responses recorded from the pinned RAGFlow version; re-record on upgrade | Async, bounded timeouts, no drift hidden inside an SDK |
| LLM (target) | `mistralai` Python SDK against the EU endpoint; model `mistral-large-*` dated version in config, never `-latest` in production | Pin model string in `config/models.toml` | Reproducible evals |
| LLM (Phase 0, active) | Scaleway Generative APIs (Paris) via OpenAI-compatible client (`openai` SDK with custom base URL), model `deepseek-v4.1-flash` for chat, rewrite and judge | Pin the served model name; Scaleway names are not dated, so the startup check accepts them when they contain no `latest` | Decided Oct 18, 2026: the Mistral workspace had no API quota and no Large tier during Phase 0; Scaleway was already the designated second provider. Mistral code and config stay in place, inactive, behind a `[llm] provider` switch |
| Fallback LLM | Whichever of the two EU providers is not active, for every tenant, switched on by `[llm] eu_failover` (off while the Mistral account has no API quota, findings M2). Then, **for a tenant with the external-models entitlement only**, OpenRouter through the same client as its external models, with zero-data-retention routing, the tenant's first enabled external model, its cost counted against the tenant's spend cap; every other tenant stays EU-only (owner decision 2, Oct 22, 2026; architecture §5.2 step 9). Failover happens when the call fails to open with a 5xx, a 429 or a timeout (`app.llm.factory.LLMRouter.answer_with_failover`) | Pin model string | Second EU provider; external failover per tenant, under the acceptance the tenant already signed for external models |
| External models (Phase 1a) | OpenRouter through its EU endpoint (`https://eu.openrouter.ai/api/v1`; `eu.openrouter.ai` is the only external host allow-listed) via the same OpenAI-compatible client with zero-data-retention routing and provider data collection denied on every request; models `openai/gpt-6.1-sol`, `anthropic/claude-opus-5.5` | Pin model slugs; ZDR flag asserted by a test | Owner decisions Oct 18 and 19, 2026 (architecture §14, compliance addendum); the EU endpoint keeps the API hop in the EU, upstream vendors may process outside it; per-tenant opt-in |
| Identity (Phase 1+) | Authentik, official Compose; the API validates its access tokens with PyJWT against the issuer's JWKS | Pin image tag (`infra/authentik/VERSION`) | Per the architecture document; not used in Phase 0. From P1a-02 the API is Authentik's only client for sign-in links (Phase 1a findings A6) |
| Email (Phase 1+) | Scaleway Transactional Email, region fr-par, as the primary (SMTP relay `smtp.tem.scw.cloud`, HTTP API `api.scaleway.com/transactional-email/v1alpha1/regions/fr-par`); Mailgun EU region (`smtp.eu.mailgun.org`, `api.eu.mailgun.net`) as an optional backup, switched on only by configuration and only after its DPA is filed. The API and workers send through the primary's HTTP API from one module (`app.core.mail`, Phase 1b); Authentik's email stage, which only speaks SMTP, relays through the primary's SMTP endpoint with a project-scoped credential on the same sending domain. Owner decision Oct 20, 2026, reversing the Oct 19 choice of Mailgun as sole provider: the primary stays with the hosting provider, under the Scaleway DPA already in place, and the sub-processor list does not grow unless the backup is activated | Scaleway API version pinned in `config/models.toml` (`[mail.scaleway] api_version = "v1alpha1"`, P1b-11); no provider SDK, `httpx` as for every other provider; exactly one provider active at a time (`[mail] provider`). The API's key is `SCALEWAY_TEM_API_KEY`, a key scoped to Transactional Email, not the Generative APIs key | Sign-in links, invitations and operator notices; one active provider for Authentik and the API |
| Token counting (Phase 1b) | `deepseek-tokenizer` (PyPI, MIT, pure Python, no dependencies): the DeepSeek V4 series `tokenizer.json` inside the wheel, so it works offline; counts the history and context caps (`app.chat.tokens`, P1b-15 f) in place of the Phase 0 estimate of four characters per token | `~=0.3.0`, wheel hash in `uv.lock`; the code was read before adoption (a JSON load and a byte-level BPE, no network, no code execution from data) | The active and eval model is `deepseek-v4.1-flash`. A third-party package, not DeepSeek's own: its file could not be compared with DeepSeek's published tokenizer from the build container (findings 1b E2-7). For Qwen and the external models it is a close stand-in; the caps are our own budgets |
| Reverse proxy | Caddy | Pin image tag | Automatic TLS, minimal config |
| Containers | Docker Compose, one file per environment under `infra/` | Compose v2 | Matches RAGFlow's own distribution |
| Observability | Structured JSON logs to stdout; Prometheus metrics endpoint; Grafana + Loki in `infra/monitoring` (Phase 1+) | n/a | Stays on the VPS |
| Testing | `pytest` + `pytest-asyncio` + `httpx` test client; `vitest` + Playwright for web; `@axe-core/playwright` for the web accessibility baseline (UX-02, Oct 24, 2026); the web visual-regression suite runs in the official Playwright image (UX-05) | axe 4.13.0, dev only; `mcr.microsoft.com/playwright:v1.63.0-noble` pinned by digest, matching `@playwright/test` | Standard; axe is the common WCAG rule engine and never ships to users; one image makes snapshots identical on every machine and in CI |
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
- All outbound hosts (Mistral, Scaleway including Transactional Email, OpenRouter, RAGFlow, and Mailgun only while the backup is active) are listed in `config/models.toml` and checked at startup against the allow-list, which is split into EU hosts and external hosts; the API refuses to start otherwise, and refuses an external host for a tenant without the "external models" entitlement.
- Migrations only through Alembic; schema changes never by hand.
