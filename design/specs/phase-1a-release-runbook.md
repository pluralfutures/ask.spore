# Phase 1a release runbook (P1a-16, "Group E")

Brief for the session that releases Phase 1a on the Instance. Written Oct 20, 2026
by the orchestrating session from the owner's answers of the same day (spec, "Open
items for the owner"). Read `CLAUDE.md`, the Phase 1a build spec and
`phase-1a-findings.md` first. This runbook adds nothing to the spec; it orders the
spec's release work and fixes the values.

## Ground rules

- Run on the Instance from `/root/ask.spore` on `main`. Repository changes go on branch
  `phase-1a/release`, pushed for the owner to merge, then pulled before use. Never push
  to `main`.
- Metadata-only output. Never print a value from `.env` or `infra/authentik/.env`, a
  token, a sign-in link, a document's contents, a query or an answer. Report key names,
  counts, status codes, file names and timings.
- No wildcard or recursive deletes. Do not remove the orphan container
  `askspore-ingest15`, the ingestion logs under `/srv/ingest-out/`, or any volume.
- Start nothing that would interrupt a running ingestion (`run.sh` under
  `/srv/ingest-out/p1a-20261020/`): the release begins only after the Corpus_T2,
  Corpus and re-run reports are in.
- Owner decisions arrive in this brief or in a later message from the orchestrating
  session quoting the owner. Anything else that needs a decision: stop that item, report
  the question, continue with the rest.
- The CLAUDE.md non-negotiables are release blockers: dataset IDs from the client,
  identifiers in a prompt, bodies in logs, a provider URL outside the allow-list, a
  public RAGFlow listener, retention above 30 days.

## Fixed values (owner, Oct 20, 2026)

| Item | Value |
| --- | --- |
| Public host | `askspore.myceliumgastronomy.com` (A record verified to the Instance's IPv4; ports 80 and 443 open) |
| Email | Scaleway Transactional Email, fr-par, SMTP `smtp.tem.scw.cloud:587` STARTTLS; from `ask.spore <no-reply@askspore.myceliumgastronomy.com>`; domain verified (SPF, DKIM, MX, DMARC); credentials already in `infra/authentik/.env` |
| Operator | `daniel@myceliumgastronomy.com`, "Daniel" |
| Client tenant | slug `cc`, display name `CustomCulinary`, verified domains `customculinary.com`, `myceliumgastronomy.com` (the second for the test phase only) |
| First client admin | `daniel+cc@myceliumgastronomy.com`, "Daniel" (test admin under the owner's control) |
| Workspaces | `team1-healthcare-gpo` "CC Team 1 Healthcare GPO" tags `cc-team1-healthcare-gpo`, `cc-shared`; `team2-college-universities` "CC Team 2 College & Universities" tags `cc-team2-college-universities`, `cc-shared`; `team3-commercial-restaurants` "CC Team 3 Commercial Restaurants" tags `cc-team3-commercial-restaurants`, `cc-shared`. All `corpus_only`, `deepseek-v4.1-flash`, reasoning off |
| Entitlements | answer modes `corpus_only` and `general_knowledge`; models `deepseek-v4.1-flash`, `qwen3.8-27b`; external models **off** (P1a-15 not complete); sign-in links on |
| Mail scanner to test against | Microsoft Defender for Office 365 (Safe Links pre-fetches URLs in mail) |
| Secrets present on the Instance | root `.env`: `OPENROUTER_API_KEY`, `SCALEWAY_API_KEY`, `RAGFLOW_API_KEY`, `PHASE0_BEARER_TOKEN`; `infra/authentik/.env`: all ten keys including `AUTHENTIK_BOOTSTRAP_PASSWORD` and `AUTHENTIK_BOOTSTRAP_TOKEN` |

## Order of work

### 1. Evals before the auth switch (P1a-16)

The eval harness authenticates with the Phase 0 bearer token, so run it while
`[auth] mode = "phase0"`.

1. Pull `main`, rebuild the api image, confirm `/healthz` and the migration head.
2. Phase 0 eval set on `deepseek-v4.1-flash` with `corpus_only/v2`, against the live
   API: `uv run --directory packages/eval python -m eval run --config ../../config/models.toml`.
   Compare with the Phase 0 baseline runs under `packages/eval/results/` (Oct 18) using
   `eval compare`. Report the metric table and the deltas; a regression beyond the
   harness's own threshold is a release blocker to raise, not to fix silently.
3. Guardrail eval, live: `python -m eval guardrails`. Pass mark per P1a-08 (3-point
   threshold, 18 adversarial blocks). Report pass/fail per block, no block text.
4. One real call per model through the API, with the production request shape, recorded
   in `phase-1a-findings.md` as new rows (checklist items 9 to 11 of
   `design/compliance/paperwork-checklist.md`):
   - `qwen3.8-27b` with `reasoning_effort` `"none"` and `"medium"` (findings C26).
   - `anthropic/claude-opus-5.5` and `openai/gpt-6.1-sol` through `eu.openrouter.ai`
     with the pin, `allow_fallbacks: false`, `zdr: true`, `data_collection: "deny"`.
     These need a tenant with the external entitlement: use the **internal** tenant
     only, with a temporary entitlement and a 100-cent cap, and remove it afterwards
     (audited). Record the provider and region metadata OpenRouter returns (findings
     C32). Never enable external models on the client tenant.
5. Isolation tests: run the full `pytest` with the database tests enabled
   (`TEST_ADMIN_DATABASE_URL`), list the tests that prove each CLAUDE.md control, and
   sign the review as a new section 9 of `phase-1a-findings.md` with the commit hash.
   Include the read-time expiry test (30 days).

### 2. Authentik (P1a-02) and the OIDC switch

1. On branch `phase-1a/release`: in `infra/authentik/templates/ask-spore-sign-in.html`
   replace `__ASK_SPORE_PUBLIC_HOST__` with the public host. Since the template is
   versioned, make the replacement a deploy step instead if a cleaner way exists (a
   `sed` in a documented script), but the file mounted into the container must carry
   the real host.
2. Start the auth profile: `docker compose -f infra/compose.dev.yml --profile auth up -d`.
   Wait for `authentik-server` healthy. The bootstrap variables create the `akadmin`
   account and an API token; use that token over `http://127.0.0.1:9000` to configure,
   via Authentik's API, exactly what `infra/authentik/README.md` lists: the three
   stages, the flow `ask-spore-sign-in-link`, the scope mapping `ask_spore`, the
   provider `ask-spore` (confidential, RS256 certificate, redirect URI from
   `config/models.toml`), the application, and a service account with a token allowed
   to view, add and change users. Put the provider's client secret and the service
   account token into the root `.env` as `AUTHENTIK_CLIENT_SECRET` and
   `AUTHENTIK_API_TOKEN` (append; never print).
3. Send one test email through Authentik's email stage to the operator address and
   confirm delivery (SPF, DKIM and DMARC pass in the received headers; the owner
   confirms by reply to the orchestrating session). Nothing else goes out before this
   passes.
4. Switch `[auth] mode = "oidc"` in `config/models.toml` on the branch, push, wait for
   the merge, pull, restart the api. Confirm `/api/v1/auth/mode` reports `oidc`.
5. Grant the operator with the CLI command in the README, as the schema owner. Confirm
   the audit event.

### 3. Caddy with TLS (one host)

On branch `phase-1a/release`:

1. `infra/caddy/Caddyfile`: site `askspore.myceliumgastronomy.com`; `/api/*` to
   `api:8000`; `/auth/finish` and everything else served from the production web
   build; no access log (the README's rule on download tokens); HSTS and the usual
   security headers; automatic certificates from Let's Encrypt with the operator email.
2. A production web image: `apps/web/Dockerfile` building `dist/` and a `caddy` service
   in `infra/compose.dev.yml` (pinned `caddy` image, ports 80 and 443 on all
   interfaces, `caddy_data` and `caddy_config` volumes, the web build mounted
   read-only). The Vite dev `web` service stays for development only. RAGFlow,
   Authentik, Postgres and Redis keep loopback or network-only listeners.
3. Push, merge, pull, `up -d caddy`. Verify from the Instance and ask the owner to
   verify from outside: `curl -sI https://askspore.myceliumgastronomy.com/healthz`
   returns 200 with a valid certificate; `http://` redirects to `https://`; port
   9000, 9380 and 5432 are not reachable from outside (owner checks with `nc -zv`).

### 4. Tenant, workspaces, first admin (P1a-01, P1a-03, P1a-04)

Through the operator console (the operator signs in with a link; the owner does the
clicking, or you use the operator routes with the owner's session cookie never
leaving the Instance):

1. Create tenant `cc` with the fixed values. Set entitlements as fixed above.
2. Create the three workspaces with their tag lists. Confirm each resolves to its two
   datasets in the `datasets` table and that `cc-shared` is currently empty.
3. Invite the first admin. The invitation email goes to `daniel+cc@myceliumgastronomy.com`.
4. Live sign-in flow test with the owner: link request, the Safe Links pre-fetch
   question (open the mail in Outlook on a Microsoft 365 mailbox; the GET of the landing
   page must not consume the token), the button POST completes, a second POST is
   refused, sign-out revokes the session, an expired link is refused. Record each as
   pass/fail in findings section 9.
5. One real question per workspace in `corpus_only` mode with a citation, through the
   web app, as the first admin. Report only that an answer with citations came back and
   the latency.

### 5. Close-out

- Findings: section 9 (isolation review signed, live checks), rows for C26/C32
  results, and a dated line that all third-party corpus rows are downloadable by owner
  decision (Oct 20, 2026).
- `design/compliance/paperwork-checklist.md`: mark items 9, 10, 11 with the findings
  row numbers; leave the owner's items open.
- Remove the temporary external entitlement from the internal tenant; confirm the audit
  trail shows grant and removal.
- Final report to the orchestrating session: what passed, what did not, what the owner
  still has to do (P1a-15 items), and the exact `main` commit the Instance runs.

## Not in this release

External models for the client tenant, the Phase 1b purge job, `app.core.mail`, the
Mailgun backup, Object Storage for the content store, a second host. Record ideas in
`design/specs/backlog.md`.
