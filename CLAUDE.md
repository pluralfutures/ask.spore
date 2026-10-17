# ask.spore — rules for coding sessions

Multi-tenant research chatbot with its own RAG. Read before writing code:

1. `design/Platform Architecture & Functional Design — Multi-Tenant RAG Chatbot.md` — what we are building and why.
2. `design/Compliance & Privacy Design Guide — … .md` — the SOC 2, GDPR and zero-data-retention requirements. It wins over everything else.
3. `design/Stack Decision.md` — technology choices and repo layout. Do not substitute technologies.
4. `design/specs/` — the build spec for the current phase. Build only what the current phase spec includes; its "not in this phase" list is binding.

## Non-negotiable rules

These implement compliance controls. Do not weaken them for convenience, tests or demos.

- **Dataset IDs never come from the client.** The RAGFlow retrieval call is built server-side from the tenant's package. Any endpoint that accepts dataset or document IDs from a request body is a bug.
- **No tenant, user or package identifiers in anything sent to an LLM.** The prompt contains: the system prompt, retrieved chunks with provenance (publisher, title, date, page), conversation turns, and the user's question. Nothing else.
- **No request or response bodies in logs.** Use `app.core.logging.log()` with allow-listed fields only. Never log `query`, `answer`, `prompt`, `chunk_text`, `message`, headers or tokens. Debug logging of bodies is a code-review blocker even behind a flag.
- **Every tenant-scoped table has `tenant_id`, a row-level-security policy and a `tenant_id`-first index**, from its first migration, even while there is only one tenant.
- **Cache keys are tenant-prefixed** via `app.core.cache`; no direct Redis calls elsewhere.
- **Only EU endpoints.** Provider base URLs and model names live in `config/models.toml` and are validated at startup against the allow-list. Never hard-code a provider URL or a `-latest` model alias in code.
- **Retrieval is read-only and tool-free.** The model gets no tools except, in web-search mode (Phase 2+), Mistral's own web-search tool. Crawled and web text is untrusted input and is wrapped as such in prompts.
- **RAGFlow is internal.** It has no public listener and is reached only by the API and workers with a service key from the environment. Never expose RAGFlow endpoints through our API.
- **Chat history retention is 30 days maximum.** Do not add settings that allow more.
- **Never commit secrets, `.env` files, real client documents or real queries.** Fixtures use synthetic content under `packages/eval/fixtures/`.

## Working conventions

- Python: `ruff` clean, `mypy --strict` clean on `apps/api/app`, tests pass (`uv run pytest`). Web: `pnpm lint`, `pnpm typecheck`, `pnpm test`.
- Add a test with every behaviour; isolation controls get a test that proves the negative case (cross-tenant read returns nothing, prompt contains no identifiers, log line contains no body).
- Schema changes only via Alembic migrations.
- Prompts are versioned files under `config/prompts/`; changing a prompt means a new version file and an eval run.
- Keep commits small and scoped to one spec item; reference the spec item ID (for example `P0-07`) in the commit message.
- When the design and the code must diverge, update the design document in the same PR and say why in the PR description. Do not silently drift.
- Do not start the next phase's work early, even when it looks easy. Record ideas in `design/specs/backlog.md` instead.

## Commands

```
# local stack (RAGFlow + Postgres + Redis + API + web)
docker compose -f infra/compose.dev.yml up -d
uv run --directory apps/api alembic upgrade head
uv run --directory apps/api uvicorn app.main:app --reload
pnpm --dir apps/web dev

# checks
uv run --directory apps/api ruff check . && uv run --directory apps/api mypy app
uv run --directory apps/api pytest
pnpm --dir apps/web lint && pnpm --dir apps/web typecheck && pnpm --dir apps/web test

# eval
uv run --directory packages/eval python -m eval run --config ../../config/models.toml
```

These commands are the target; if a script does not exist yet, create it as part of the spec item that needs it.
