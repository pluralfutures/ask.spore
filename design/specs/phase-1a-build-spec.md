# Phase 1a Build Spec — First Test Client

Oct 18, 2026 · Status: draft for owner review · Target duration: 5–7 weeks · Starts after the Phase 0 exit criteria hold

Source decisions: architecture document §14 and the compliance guide addendum of Oct 18, 2026. Phase 1 of the architecture document is split into 1a (this spec) and 1b (`backlog.md`).

## Goal

Put one paying test client on the platform with: real sign-in, several users, three workspaces each with its own corpus and admin-set prompt, a choice of four models with reasoning on or off, and a read-only list of the files behind each workspace with downloads. Everything the CLAUDE.md rules require for multi-tenancy exists from the first migration, even though there are two tenants (ours and the client's).

Exit criteria (all must hold):

- The test client's users sign in with emailed links, pick one of three workspaces, and get cited answers from that workspace's corpus only; the cross-workspace and cross-tenant isolation tests pass in CI.
- Each user can choose any enabled model and toggle reasoning when starting a conversation; the answer shows the model and a reasoning badge; usage and cost are recorded per tenant.
- The operator can enable external models for the client and set a spend cap; a tenant without the entitlement cannot reach OpenRouter (test).
- Each workspace shows its file list; downloads work, are audited and are capped.
- Eval set v1 on `deepseek-v4.1-flash` shows no regression against the Phase 0 baseline; the prompt-guardrail adversarial set passes.
- Compliance addendum items done: OpenRouter DPA accepted and filed, one-page TIA written, client DPA names external models and the file-download feature.

## Not in this phase

Binding. Record ideas in `backlog.md`.

- Content console, source register approval flow, crawler scheduling (Phase 1b). Ingestion stays on the Phase 0 CLI.
- Two-host deployment, Caddy TLS beyond a single host, monitoring stack, Secret Manager (Phase 1b). One Instance with Caddy TLS is enough.
- SSO connectors (Entra, Google, OIDC/SAML). Sign-in links only.
- Retention purge job (Phase 1b). The 30-day expiry applied at read time stays and gets its test in P1a-16.
- Web-search mode (Phase 2).
- User-edited workspace prompts (Phase 2). Tenant admins only.
- Per-model eval baselines. Eval runs on the default model only.
- Search or filters on the file list; source filters on queries.
- Switching workspace, model or reasoning inside an existing conversation.
- Showing reasoning text to users or storing it.
- Tenant admin dashboard (Phase 2); the admin pages here are user management, workspace prompts and defaults.

## Deployment target

The Phase 0 Instance, re-sized if the Phase 0 findings on host sizing say so. Compose adds Authentik and Caddy with TLS on a public hostname; RAGFlow stays on the Compose network only.

## Work items

Build in this order; items in a group can be parallelised. Every tenant-scoped table gets `tenant_id`, an RLS policy and a `tenant_id`-first index in its first migration.

### Group A — Tenancy and identity

**P1a-01 Tenants and users.** Tables `tenants(id, slug, display_name, verified_domains[], created_at, status)`, `users(id, tenant_id, email, role in {user, tenant_admin}, status, last_login_at, last_login_method)`, `tenant_entitlements(tenant_id, answer_modes[], enabled_models[], external_models_enabled, external_spend_cap_cents, sign_in_links_enabled)`. Phase 0's hard-coded tenant becomes a row. The request context resolves the tenant from the authenticated user and sets `app.tenant_id` on the connection. Tests: RLS blocks a cross-tenant read of users and entitlements; a request without tenant context fails closed.

**P1a-02 Authentik with sign-in links.** Authentik from the official Compose, pinned tag, with an email-link stage over the transactional email provider (Scaleway Transactional Email, fr-par, as the primary SMTP relay, with Mailgun's EU relay as an optional backup; owner decision Oct 20, 2026, after Mailgun alone on Oct 19; see `infra/authentik/README.md`). The API validates Authentik's OIDC tokens and maps the identity to a `users` row by tenant and email; unknown emails are refused without enumeration. The emailed link must not complete the login by itself: corporate mail security scanners pre-fetch links and would consume a single-use token before the user opens it. The link therefore lands on our own page that carries the token in the URL fragment (never sent to a server by a fetch), shows one button ("Click to finish logging in"), and only the button's POST submits the token to the Authentik flow. A GET of the landing URL, with or without the fragment, consumes nothing. Browser binding from the compliance guide applies to the POST. Auth success and failure write `audit_events` (closes the Phase 0 backlog item). Tests: token for a user of tenant A cannot act on tenant B; expired or reused link is refused; a GET of the link URL does not consume the token and a later POST succeeds; a second POST with the same token is refused; audit event written with method.

**P1a-03 Operator console, minimum.** Operator-only routes and pages: create tenant, invite first admin, set entitlements (answer modes, enabled models, external models on/off with spend cap, sign-in links on/off), and an operator notices list (fed by P1a-07 and P1a-10). Enabling external models requires an acceptance reference (client DPA document and date) that is stored on the entitlement and in the audit event; the route refuses to enable without it. Operator role lives outside tenant RLS and is checked by a separate dependency. Every change writes an audit event with before and after values. Tests: a tenant admin cannot reach operator routes; entitlement change audited.

### Group B — Workspaces

**P1a-04 Workspace model.** Table `workspaces(id, tenant_id, slug, name, tag_ids[], default_mode, default_model, default_reasoning, created_at)` and `workspace_prompts(id, tenant_id, workspace_id, version, text, author_user_id, created_at)`; the active prompt is the latest version. Operator assigns tags per workspace in the package builder; tags may repeat across a tenant's workspaces (common corpus). Conversations gain `workspace_id`, `model`, `reasoning` columns, all fixed at creation; messages record `model` and `reasoning`. Tests: resolving a workspace's dataset IDs never reads the request body; a tenant-B user cannot read tenant-A workspaces; two workspaces sharing a tag resolve to overlapping dataset sets and a document in both appears once after retrieval de-duplication.

**P1a-05 Workspace-scoped orchestration.** The orchestrator takes the conversation's workspace and retrieves from that workspace's datasets only. Cache key becomes `tenant_id + workspace_id + mode + model + reasoning + prompt_version + normalised query + corpus version` (and gains the retrieval settings from the Phase 0 backlog item). Audit event records workspace, model, reasoning. Tests: the package-enforcement test from architecture §8 run per workspace (query matching only workspace-B documents from a workspace-A conversation returns nothing); cache miss on a prompt version change.

**P1a-06 Prompt layering.** `config/prompts/corpus_only/v2.md` and `general_knowledge/v1.md` gain a delimited slot for the workspace's additional instructions, marked as tenant-authored and lower priority than the platform rules. `app.chat.prompts` renders the slot from the active `workspace_prompts` row, length-capped (2,000 characters), with delimiter characters escaped. Tests: rendered prompt contains the block inside the delimiters only; empty block renders cleanly; the prompt-content test still proves no tenant, user, workspace or dataset identifiers are added by the code path.

**P1a-07 Tenant-name flag.** On every saved workspace prompt the API matches the text against the tenant display name, verified domains and the tenant's user names and emails (case-insensitive, whole-word). A match writes an `audit_events` row and an operator notice; the save succeeds and the user sees nothing. Tests: match produces notice and audit row, no response field reveals it; non-match produces nothing.

**P1a-08 Prompt-guardrail eval.** `packages/eval/fixtures/adversarial_prompts/` with at least 15 hostile additional-instructions blocks (ignore the context, answer from memory, drop citations, reveal the system prompt, answer a different workspace's question). `python -m eval guardrails` runs eval items under each block and fails if abstention or citation behaviour degrades beyond the compare threshold. Runs in CI on prompt changes.

### Group C — Models and reasoning

**P1a-09 Model catalogue and entitlement.** `config/models.toml` gains `[catalogue]` entries per model (provider, id, display name, reasoning switch kind, price per million tokens in and out, `external = true/false`) and splits `[allow_list]` into `eu_hosts` and `external_hosts`; `eu.openrouter.ai`, OpenRouter's EU endpoint, joins `external_hosts` (owner decision Oct 19, 2026, replacing `api.openrouter.ai`; findings C25). Add `qwen3.8-27b` to the Scaleway section. The orchestrator refuses a model not in the tenant's `enabled_models`, and refuses any external model when `external_models_enabled` is false, before any outbound call. Tests: startup rejects an unlisted host; disabled model and external-without-entitlement both fail closed with no HTTP call (asserted with a mocked transport).

**P1a-10 OpenRouter client and spend cap.** `app.llm.openrouter` on the OpenAI-compatible path, same interface as the Scaleway client, with the zero-data-retention routing option set on every request, pinned slugs, timeouts, one retry on 5xx. Usage per message is priced from the catalogue into `usage_ledger(tenant_id, month, model, tokens_in, tokens_out, cost_cents)`. At 80 percent of the cap an operator notice is written once per month; at 100 percent new conversations on external models are refused with a user-facing notice and fall back to the workspace default model. Tests: serialised request carries the ZDR flag and no tenant, user or workspace identifiers; cap at 100 percent falls back and audits; reasoning parameter mapped per model kind.

**P1a-11 Reasoning switch.** Reasoning on or off per conversation maps to: DeepSeek and Qwen thinking enabled or disabled; GPT and Claude reasoning effort medium or none. Reasoning content in the stream is discarded, never persisted. Tests: stream with reasoning segments yields only the answer text; `reasoning` is stored on the message; the badge data is in the API response.

### Group D — Web app

**P1a-12 Conversation start panel.** New conversation requires workspace (hidden when the tenant has one), model (hidden when one is enabled) and reasoning toggle, pre-filled from the workspace defaults. The conversation header shows the workspace label, model name and reasoning badge; none can be changed after the first message. Tests: vitest for the panel states; Playwright for a start-to-answer flow.

**P1a-13 Tenant admin pages.** Users: invite, deactivate, role; last login and method. Workspaces: edit additional instructions (shows version history, no revert yet), set default mode, model and reasoning among enabled options. Retention shortening from 30 days. Tests: a `user` role cannot open admin pages; saving a prompt creates a new version.

**P1a-14 Workspace file list and downloads.** Per workspace, a page listing PDF, DOCX and PPTX files in the workspace's tags with publisher, title, publication date, canonical link and ingestion date, from the source register; crawled sites appear once with page count. Migration adds `sources.downloadable` (boolean, not null, default false); the ingestion CLI sets it from a `downloadable` manifest column, and the operator console can toggle it per source (audited). A file has a download action only when `downloadable` is true; otherwise the row shows the canonical link. Downloads are served through a signed URL valid for 60 seconds, audited (`download` event with source_id), capped at a configurable number per user per day (default 50). Tests: a file in a tag outside the workspace is neither listed nor downloadable, even by direct URL; a listed file with `downloadable = false` is refused by direct URL; cap enforced; audit event written; API response carries no dataset or document IDs beyond our own register UUIDs.

### Group E — Compliance and release

**P1a-15 Compliance paperwork.** OpenRouter DPA with SCCs accepted and filed; transfer impact assessment in `design/compliance/` naming OpenRouter, the upstream vendors for the enabled slugs, destination countries, supplementary measures and a review date; client DPA draft names external models (sub-processor and transfer mechanism), the licence-gated download feature and the 30-day cap; sub-processor list updated; trust-page text drafted; the Scaleway DPA and written zero-retention confirmation left open in Phase 0 (findings M2) filed. Checklist in the compliance guide updated. The external-models entitlement is not enabled for any tenant until this item is done.

**P1a-16 Release checks.** Phase 0 eval set on `deepseek-v4.1-flash` compared against the Phase 0 baseline; guardrail eval passing; isolation tests reviewed and signed in `design/specs/phase-1a-findings.md`; a test proving that conversations and messages older than 30 days are not returned by any read route (read-time expiry, pending the Phase 1b purge job); CLAUDE.md rules verified by a reviewer.

**Status: Phase 1a closed on Oct 21, 2026** (findings §10 to §12; P1a-15 paperwork items carried by owner decision, see the compliance checklist).

## Open items for the owner

- Confirmed Oct 19, 2026: Scaleway `qwen3.8-27b` (reasoning efforts none, low, medium, xhigh) and OpenRouter `openai/gpt-6.1-sol` (provider azure, EU region) and `anthropic/claude-opus-5.5` (provider amazon-bedrock, eu-west-1), reached through `https://eu.openrouter.ai/api/v1`. Prices and the USD to EUR rate (0.90) are in `config/models.toml` with the date. Findings C26, C30, C31; the provider is pinned, the regions are to be verified in P1a-15 (C32).
- Confirmed Oct 19, 2026: per-user daily download cap 50 (the default); external-model spend cap for the test client EUR 30.00 per month (3,000 cents), set in the operator console when external models are enabled, after P1a-15.
- Confirmed Oct 19, 2026: the test client's three workspaces. Each has its own tag plus the shared tag `cc-shared` (the common corpus). Tags renamed Oct 20, 2026 to the lowercase-hyphen form the tag validator requires and added to `config/tags.toml` (findings E1); workspaces are created in the operator console with `tag_ids` = own tag + `cc-shared`.
  - "CC Team 1 Healthcare GPO": `cc-team1-healthcare-gpo`, `cc-shared`
  - "CC Team 2 College & Universities": `cc-team2-college-universities`, `cc-shared`
  - "CC Team 3 Commercial Restaurants": `cc-team3-commercial-restaurants`, `cc-shared`
- Confirmed Oct 20, 2026, withdrawn Oct 21, 2026 (the client will not use Outlook; the actual mail client and link scanner are to be confirmed with the client's IT contact, backlog): the test client uses Microsoft Defender for Office 365; the post-click landing page is checked against its Safe Links pre-fetch before launch (P1a-16).
- Confirmed Oct 20, 2026, release inputs (P1a-16; secrets stay in the Instance `.env` files, never here):
  - Public host `askspore.myceliumgastronomy.com`, which is also the email sending domain (Scaleway Transactional Email, fr-par; A and MX records on the same name); from address `ask.spore <no-reply@askspore.myceliumgastronomy.com>`.
  - Operator: `daniel@myceliumgastronomy.com`, "Daniel" (internal tenant).
  - Test client tenant: slug `cc`, display name "CustomCulinary", verified domains `customculinary.com` and, for the test phase only, `myceliumgastronomy.com`; `cc-shared` stays empty for now (owner decision Oct 21, 2026), so each workspace retrieves from its own tag only until shared files are tagged; first admin `daniel+cc@myceliumgastronomy.com`, "Daniel", a test admin under the owner's control, because one sign-in identity belongs to exactly one tenant and the operator address cannot also be a client admin. `myceliumgastronomy.com` is removed from the tenant's verified domains before the client's own admin is invited.
  - Workspaces as above, each `corpus_only`, `deepseek-v4.1-flash`, reasoning off, slugs `team1-healthcare-gpo`, `team2-college-universities`, `team3-commercial-restaurants`.
  - Entitlements: both answer modes; models `deepseek-v4.1-flash` and `qwen3.8-27b`; external models off until P1a-15 is complete (then spend cap 3,000 cents and the DPA reference); sign-in links on.
  - GDPR roles: processor for client user data, controller for the corpus and own logs (compliance checklist item 6).
