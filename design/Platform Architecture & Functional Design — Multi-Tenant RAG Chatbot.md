# Platform Architecture & Functional Design — Multi-Tenant RAG Chatbot

Oct 17, 2026 · Draft for review

Companion to [Compliance & Privacy Design Guide](./Compliance%20%26%20Privacy%20Design%20Guide%20%E2%80%94%20Multi-Tenant%20RAG%20Chatbot%20%28Public%20Sources%20Only%29.md). That document sets the SOC 2, GDPR and ZDR requirements; this one describes the system that satisfies them. Where the two disagree, the compliance guide wins and this document should be amended.

This is a design, not an implementation plan. Open scoping questions are collected at the end; several design choices below are marked as provisional pending answers.

---

## 1. Summary

A hosted research assistant. Business clients (tenants) log in, ask questions in a chat interface, and receive cited answers drawn only from a curated corpus: licensed third-party PDFs, crawled public web pages and our own DOCX/PPTX analysis. There is no client upload and no open-web browsing at query time.

Key decisions:

| Decision | Choice | Rationale |
| --- | --- | --- |
| Retrieval engine | RAGFlow, self-hosted, internal only | Strong document parsing (DeepDoc) for PDF/DOCX/PPTX, built-in chunking, hybrid search, retrieval API with per-dataset scoping |
| Corpus model | One shared RAGFlow instance; one dataset (knowledge base) per entitlement tag | Mirrors the compliance guide's "shared corpus, entitlement filter" model; avoids per-tenant re-ingestion |
| Tenant boundary | Our own application layer, not RAGFlow's tenant model | RAGFlow's users/teams are an admin convenience, not a security boundary we would want to expose to clients |
| Generation | Our application calls the LLM directly; RAGFlow is used for retrieval only (provisional, see §5.3) | Full control of prompt contents, ZDR endpoint, region pin, citation format, streaming and logging |
| LLM provider | Mistral (La Plateforme, EU) primary; Scaleway Generative APIs (Paris) as second provider and fallback | Both EU-hosted; OpenAI-compatible interfaces; contractual no-retention available |
| Embeddings | Self-hosted on the VPS (RAGFlow bundled model, e.g. bge-m3) by default; Mistral `mistral-embed` as alternative | Keeps corpus text off any third party during ingestion; corpus is multilingual |
| Identity | Self-hosted OIDC provider (Keycloak or Zitadel) with per-tenant realms/organisations; client SSO federation optional | SSO per tenant, MFA, RBAC and audit events without a non-EU identity vendor |
| Hosting | EU VPS (two hosts recommended: app + RAGFlow), Docker Compose, EU object storage for backups | Simplicity at launch scale; clean upgrade path to Kubernetes if needed |

---

## 2. Actors and roles

| Actor | Who | What they do |
| --- | --- | --- |
| Tenant user ("analyst") | Client employee | Chat, browse history, view sources, give feedback |
| Tenant admin | Client-side lead | Manage their users, set history retention within allowed range, view tenant usage |
| Tenant auditor (optional) | Client compliance | Read-only view of tenant audit log and retention settings |
| Platform operator | Our team | Create tenants, assign entitlements, manage users across tenants, support access (time-boxed) |
| Content editor | Our research team | Add sources to the register, upload analysis, trigger crawls, approve ingestion, process takedowns |
| Content reviewer | Our research lead | Approve licence basis, publish sources to entitlement tiers |
| Platform security | Our security lead | Review audit logs, alerts, run evaluations, manage keys and vendors |

Tenant-side roles are enforced by our application. Operator-side roles are enforced in the admin console and mapped to RAGFlow service credentials that clients never see.

---

## 3. Logical architecture

```mermaid
flowchart LR
  subgraph Client
    B[Browser]
  end

  subgraph EU VPS A — Application tier
    RP[Reverse proxy / TLS\nCaddy or Traefik]
    WEB[Chat web app]
    API[Platform API\nauth, tenancy, entitlements,\nchat orchestration, audit]
    IDP[OIDC provider\nKeycloak / Zitadel]
    PG[(PostgreSQL\ntenants, users, chats,\nsource register, audit)]
    RD[(Redis\nsessions, rate limits,\ntenant-keyed cache)]
    WRK[Workers\ncrawler, ingestion,\nretention, eval]
  end

  subgraph EU VPS B — Retrieval tier (private network only)
    RF[RAGFlow server\nparsing, chunking,\nhybrid retrieval API]
    ES[(Elasticsearch / Infinity\nindex)]
    MIO[(MinIO\noriginal files)]
    MY[(MySQL\nRAGFlow metadata)]
    EMB[Embedding model\nself-hosted]
  end

  subgraph EU LLM providers
    MIS[Mistral La Plateforme\nEU, ZDR]
    SCW[Scaleway Generative APIs\nParis, no retention]
  end

  OBJ[(EU object storage\nencrypted backups)]

  B -- HTTPS --> RP --> WEB
  WEB --> API
  API <--> IDP
  API <--> PG
  API <--> RD
  API -- retrieval only\n(dataset IDs injected) --> RF
  API -- query + chunks + system prompt --> MIS
  API -. fallback .-> SCW
  WRK --> RF
  WRK <--> PG
  RF <--> ES
  RF <--> MIO
  RF <--> MY
  RF <--> EMB
  PG -. nightly .-> OBJ
  MIO -. nightly .-> OBJ
```

Boundaries that matter:

- **Clients only ever talk to the reverse proxy.** RAGFlow, its databases and MinIO are bound to a private network (WireGuard or the provider's private VLAN) and have no public listener.
- **The platform API is the only RAGFlow client.** It holds one RAGFlow service API key per environment. Tenant identity never reaches RAGFlow; only the list of dataset IDs the tenant is entitled to.
- **The only outbound call carrying query data** is the generation request to the LLM provider. Everything else stays on the two hosts.

---

## 4. Components

### 4.1 Chat web app

Single-page app served by the platform API host. Responsibilities: login via OIDC, chat UI with streaming, citation panel, history, tenant admin pages. No business logic; no direct calls to RAGFlow or the LLM.

### 4.2 Platform API

The heart of the system. Owns:

- **Authentication**: validates OIDC tokens from the identity provider, resolves user → tenant → roles.
- **Tenancy and entitlements**: tenant record, entitlement set (list of tags), feature flags, retention settings.
- **Chat orchestration** (§5): query rewriting, retrieval, prompt assembly, LLM call, citation mapping, streaming, persistence.
- **Guardrails**: per-user and per-tenant rate limits, bulk-extraction detection, output scanning.
- **Audit log** writer (§8).
- **Admin and content-ops APIs** consumed by the console.

Suggested stack: a typed backend (TypeScript/NestJS or Python/FastAPI), PostgreSQL with row-level security on all tenant-scoped tables, Redis for sessions and limits.

### 4.3 Identity provider

Self-hosted Keycloak or Zitadel on the application host.

- One realm (Keycloak) or organisation (Zitadel) per tenant, so that tenant SSO federation (SAML/OIDC to the client's own IdP) can be configured without touching other tenants.
- MFA mandatory for operator accounts and tenant admins; configurable per tenant for analysts.
- Emits login, logout, failed-login and admin events to the audit log.
- Operator accounts live in a separate internal realm with hardware-key MFA.

### 4.4 RAGFlow (retrieval tier)

Deployed from the official Docker Compose on its own host. Used for:

- **Parsing**: DeepDoc for PDF (layout, tables, figures with captions), native DOCX and PPTX parsing, HTML/Markdown for crawled pages.
- **Chunking**: per-dataset chunking method (e.g. "paper" or "book" for reports, "presentation" for PPTX, "naive" for web pages); chunk size and overlap tuned per source type.
- **Indexing**: hybrid dense + full-text index in Elasticsearch (default) or Infinity.
- **Retrieval**: the HTTP retrieval endpoint, called with a list of dataset IDs, the query, `top_k`, similarity threshold and optional keyword re-ranking.

Not used for: end-user authentication, chat history, the client-facing chat assistant (provisional), or anything exposed to clients. The RAGFlow web UI is reachable only over the private network and only by content and platform roles.

**Dataset layout**: one RAGFlow dataset per entitlement tag, named by tag (`tier-public`, `tier-premium`, `pkg-<client-slug>`, `internal-analysis`). A document that belongs in several tiers is linked into each (RAGFlow supports uploading the same file to multiple datasets; the source register records the mapping). Dataset IDs are stored in the entitlement table in PostgreSQL; the API never accepts dataset IDs from the client.

### 4.5 Workers

Background processes on the application host:

- **Crawler**: scheduled crawls of registered sites. Honours robots.txt and the EU text-and-data-mining opt-out signals, respects crawl delay, stores raw HTML plus a cleaned Markdown rendering, records fetch date and hash. Candidate tooling: Crawl4AI or Scrapy with a readability pass. Produces files that are then uploaded to the right RAGFlow dataset.
- **Ingestion**: moves approved source-register entries into RAGFlow (upload, trigger parse, poll status), records chunk counts and parse errors back in the register.
- **Retention**: nightly job applying chat-history TTL per tenant, log retention, cache expiry, and the source-level delete cascade for takedowns.
- **Evaluation**: runs the versioned eval set against the current retrieval and prompt configuration on every change (§9).

### 4.6 Data stores

| Store | Content | Tenant scoping |
| --- | --- | --- |
| PostgreSQL (app) | Tenants, users, roles, entitlements, conversations, messages, citation sets, feedback, source register, audit log, usage aggregates | Row-level security keyed on `tenant_id`; audit and source register are operator-only |
| Redis | Sessions, rate-limit counters, semantic/answer cache | Every cache key prefixed with `tenant_id` |
| RAGFlow (MySQL, ES/Infinity, MinIO) | Corpus only: files, parsed text, chunks, embeddings | Not tenant-scoped; scoped by dataset = entitlement tag |
| EU object storage | Encrypted nightly backups of PostgreSQL, MinIO and index snapshots | Per-tenant purge of history tested quarterly |

---

## 5. Query pipeline

### 5.1 Request flow

1. **Auth and context**: API validates the token, loads tenant, user, roles, entitlement dataset IDs, retention and feature flags.
2. **Guardrails in**: rate limit check (user, tenant), input length cap, bulk-extraction heuristics (query cadence, near-duplicate queries, pagination-like patterns).
3. **Conversation context**: load the last N turns of this conversation (bounded by tokens).
4. **Query rewriting** (optional, small model): turn a follow-up such as "and in Germany?" into a standalone retrieval query using the conversation context. Runs against the EU LLM with the same ZDR terms.
5. **Retrieval**: call RAGFlow retrieval with the entitled dataset IDs, rewritten query, `top_k` (e.g. 8–12 after re-ranking), similarity threshold. Optional user-selected filters (publisher, date range, source type) are translated to RAGFlow document-level filters or applied post-retrieval using source-register metadata.
6. **Chunk selection**: de-duplicate overlapping chunks, cap total context tokens, attach provenance (publisher, title, date, entitlement tag, source ID, page/slide) from the source register.
7. **Prompt assembly**: system prompt (research-assistant behaviour, cite-or-abstain rule, no-speculation rule), numbered context chunks, conversation turns, user query. No tenant name, user identifier or entitlement information in the prompt.
8. **Generation**: streamed call to the primary EU provider; automatic failover to the secondary on 5xx/timeouts. Model version pinned in configuration.
9. **Guardrails out**: scan the stream for system-prompt leakage and for strings matching other tenants' identifiers; truncate on bulk-reproduction patterns (very long verbatim spans from a single licensed source).
10. **Citation mapping**: map `[n]` markers to the chunk set; drop markers that reference nothing; flag answers with no citations as "unsupported" in the UI.
11. **Persist**: message, answer, citation set (source IDs + chunk IDs + offsets), token counts, latency, model version. Write audit event.
12. **Cache**: store answer keyed by `tenant_id + normalised query + entitlement set hash + corpus version`; short TTL.

### 5.2 Abstention and honesty

The system prompt instructs the model to answer only from supplied chunks and to say when the corpus does not cover the question. Retrieval results below the similarity threshold yield a "nothing relevant found" response without calling the LLM, which also saves cost and keeps weak answers out of history.

### 5.3 Why generation sits in our API, not in RAGFlow chat assistants (provisional)

RAGFlow can host "chat assistants" bound to datasets and call the LLM itself. That path is faster to stand up. We recommend owning generation in the platform API because:

- We control exactly what leaves the VPS (data minimisation at the model boundary is a compliance control).
- We control the provider, endpoint region, failover and model pinning in one place.
- Citations, streaming format and abstention behaviour are ours to test and version.
- Chat history lives in our tenant-scoped PostgreSQL, not RAGFlow's MySQL.

If speed to first demo matters more than control, Phase 0 (§11) can use RAGFlow chat assistants per entitlement tier behind our API, then migrate.

---

## 6. Content pipeline

### 6.1 Source register

PostgreSQL table, the single source of truth for what is in the corpus and why. Fields: source ID, type (PDF, web, DOCX, PPTX), URL or file hash, publisher, title, publication date, licence basis (licence name, permission letter reference, or "own work"), entitlement tags, crawl/upload date, review date, status (proposed, approved, ingested, withdrawn), RAGFlow document IDs per dataset, takedown reference if any.

No document reaches RAGFlow without an approved register row. This is both the licensing defence and the index for erasure.

### 6.2 Ingestion flows

| Source type | Flow |
| --- | --- |
| Third-party PDF | Editor uploads to the register with licence basis → reviewer approves → worker uploads to the tagged datasets → RAGFlow parses (DeepDoc, "paper"/"book" method) → chunk count and errors recorded → spot-check in the RAGFlow UI → status "ingested" |
| Crawled website | Editor registers the site, scope rules and crawl schedule → worker checks robots.txt and TDM opt-out, crawls, renders Markdown, computes hashes → changed pages are re-ingested, removed pages are withdrawn → register updated per page |
| Own analysis (DOCX/PPTX) | Editor uploads with target tags → ingested with "naive"/"presentation" method → optional metadata (project, client package) attached |

Re-ingestion is versioned: a new parse creates new chunk IDs, old chunks are withdrawn, stored citations keep pointing at the old chunk ID and are shown as "superseded" in the UI.

### 6.3 Withdrawal and takedown cascade

A single job per source ID: delete the document from every RAGFlow dataset it is in (which removes file, parsed text, chunks and embeddings), purge cache entries, mark the register row withdrawn with reason and date, and flag citations in stored chat history as withdrawn. Target window: 10 working days from a valid request, immediately for licence breaches we identify ourselves.

### 6.4 Crawler policy

- Respect robots.txt, `noindex`/`noai` style directives and TDM reservation headers; keep a per-site allow decision in the register.
- Identify with a descriptive user agent and contact address.
- Rate-limit per host; never crawl behind logins; strip tracking parameters; skip pages that match obvious special-category patterns (health, religion, politics about named individuals) unless a reviewer whitelists them.
- Store the HTML snapshot for provenance; serve users only excerpts and links.

---

## 7. Functional specification

### 7.1 Analyst features (MVP)

- **Chat** with streaming answers; markdown rendering; stop generation.
- **Citations**: numbered inline markers; side panel listing sources with publisher, title, date, page/slide and the exact excerpt used; click-through to a source viewer that shows the chunk in context (PDF page render for PDFs, cleaned text for web pages). Full documents are shown only where the licence permits; otherwise excerpt and external link.
- **Conversation history**: list, search by title, rename, delete (hard delete, immediate), export a single conversation as PDF/Markdown with citations.
- **Follow-up questions** and suggested questions generated from the retrieved sources.
- **Source filters**: restrict a query to publishers, date range, source type or a named package.
- **Feedback**: thumbs up/down with optional comment per answer; feeds the eval set after review.
- **Transparency**: a persistent "AI-generated, verify against cited sources" notice; a corpus page listing which publishers and packages the tenant can query and when each was last updated.

### 7.2 Tenant admin features (MVP)

- Invite, deactivate and role-assign users; see last login.
- Choose chat-history retention within the allowed range (0 to 30 days by default; platform may allow longer per contract).
- Usage dashboard: queries per day, active users, top sources (no query text).
- Download tenant audit log (auth and admin events).
- Configure SSO federation (later phase; operator-assisted at first).

### 7.3 Content operations console (MVP)

- Source register CRUD with approval workflow and licence file attachment.
- Crawl management: register sites, scope, schedule; see last crawl, page counts, blocked pages and why.
- Ingestion status per source, parse errors, chunk previews (via link into the private RAGFlow UI).
- Takedown queue with SLA timer.
- Entitlement tag management and the tier-to-dataset mapping.

### 7.4 Platform operator console (MVP)

- Tenant lifecycle: create, suspend, terminate (triggers purge cascade with certificate of deletion for history and account data).
- Entitlement assignment per tenant; feature flags; retention bounds.
- Cross-tenant aggregates only: query volumes, latency, cost per provider, error rates. No per-tenant query text.
- Vendor and model configuration: provider endpoints, model pins, failover order, prompt template versions.
- Evaluation results and regression gate status.
- Support access: time-boxed impersonation-free "view tenant settings" mode; any access is logged and visible to the tenant.

### 7.5 Later-phase features (not MVP)

- Shared conversations and annotations within a tenant.
- Saved "briefs": pinned answers assembled into a document.
- Alerting: notify a tenant when new sources matching a saved query are ingested.
- Multi-language answers (query in one language, sources in another) — depends on embedding model choice.
- API access for tenants to integrate into their own tools, with the same entitlement enforcement.
- Per-tenant private packages with a separate RAGFlow dataset and, if contractually required, a separate RAGFlow instance.

---

## 8. Security and isolation controls (implementation view)

This section states how the compliance guide's controls are realised; it does not restate why.

| Control | Realisation |
| --- | --- |
| Entitlement enforcement | Dataset IDs resolved server-side from the entitlement table; the retrieval call is built by the API only. CI test: a fixture tenant with tag A issues queries known to match only tag-B documents and must receive nothing |
| Query and history isolation | PostgreSQL row-level security on every tenant table; the API sets `tenant_id` per transaction from the token, never from request parameters. Integration test asserts cross-tenant reads return zero rows |
| Cache isolation | Redis keys prefixed by tenant; a lint rule rejects cache calls without the tenant prefix helper |
| Data minimisation at the model boundary | One prompt-builder module; prompt template under version control; unit test asserts no tenant/user identifiers appear in the serialised request |
| Region and ZDR pin | Provider base URLs and model names in configuration with an allow-list; startup check refuses non-EU endpoints; ZDR letter reference stored next to the configuration |
| Encryption | TLS 1.2+ at the proxy and between hosts (WireGuard); disk encryption on both VPS; PostgreSQL and MinIO backups encrypted with a platform key; per-tenant key for chat history if the provider's KMS makes it practical |
| Metadata-only logs | Structured logging with an explicit allow-list of fields; request and response bodies never logged; linter rule and code-review checklist item |
| Rate limits and extraction detection | Redis token buckets per user and tenant; anomaly rules (queries per minute, verbatim overlap of outputs with a single source, sequential pagination-like queries) raise alerts and apply temporary throttling |
| Prompt-injection resistance | Retrieval is read-only; no tools; crawled text is wrapped as untrusted context in the prompt; output scanner for system-prompt leakage |
| Audit log | Append-only table plus daily export to write-once object storage; events: auth, admin actions, entitlement changes, source-register changes, takedowns, support access, every query (metadata and cited chunk IDs, not text, unless the tenant opts in) |
| Secrets | Provider API keys, RAGFlow service key and database credentials in a secrets manager or encrypted environment store; rotated on schedule and on staff departure |
| Hardening | Both hosts: SSH keys only, firewall default-deny, automatic security updates, fail2ban, container images pinned by digest, weekly vulnerability scan, annual pentest |

---

## 9. Quality, evaluation and observability

- **Eval set**: 100–300 question/answer pairs with expected source IDs, built from our own analysis and licensed sources. Versioned in the repo. Metrics: retrieval hit rate at k, citation precision, answer faithfulness (LLM-judged against the chunks, using the EU provider), abstention correctness.
- **Regression gate**: eval runs on every change to chunking, embedding model, prompt template, retrieval parameters or LLM model version; a drop beyond a threshold blocks deployment.
- **Observability**: metrics (latency per stage, tokens, provider errors, cache hit rate), traces per request with tenant ID only, alerts on error rate and on guardrail triggers. All telemetry stays on the VPS (Prometheus/Grafana/Loki or equivalent); no SaaS APM that receives bodies.
- **Cost tracking**: tokens per tenant per day, per provider, with budget alerts.

---

## 10. Deployment and operations

- **Environments**: dev (local Compose), staging (one small VPS), production (two VPS). Staging uses synthetic queries and a subset corpus; never real client history.
- **Hosts**: application host (proxy, web, API, IdP, PostgreSQL, Redis, workers, monitoring) and retrieval host (RAGFlow stack with embedding model). RAGFlow with Elasticsearch and a local embedding model wants at least 16 GB RAM and 4 vCPUs; the application host can start smaller. Sizing is revisited after load testing.
- **Networking**: private network between hosts; public ingress only on 443 on the application host.
- **Backups**: nightly encrypted dumps of PostgreSQL and RAGFlow stores to EU object storage; weekly restore test; backup retention aligned with the compliance guide's retention table; per-tenant purge procedure documented and tested.
- **Upgrades**: RAGFlow pinned to a tested version; upgrade on staging with the eval gate before production.
- **Incident response**: runbooks for provider outage (failover), index corruption (restore from snapshot), suspected cross-tenant leak (freeze, investigate from audit log, notify per DPA window).
- **Capacity path**: if load outgrows the two hosts, the same containers move to a managed Kubernetes in an EU region; RAGFlow supports Helm deployment.

---

## 11. Phasing

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| 0 — Proof of value (4–6 weeks) | RAGFlow on one VPS, a sample corpus, RAGFlow chat assistant per tier, a thin login and chat UI, Mistral EU endpoint | Internal team and one friendly client can get cited answers; eval set v1 exists |
| 1 — MVP (8–12 weeks) | Platform API with tenancy, entitlements, own generation path, history, citations, content console, source register, audit log, retention jobs, IdP, two-host deployment | Compliance guide's "before first client login" checklist complete; first paying tenants |
| 2 — Scale and assurance | Tenant SSO federation, tenant admin dashboard, extraction detection tuning, provider failover, trust page, SOC 2 observation window starts | SOC 2 Type I; three or more tenants |
| 3 — Depth | Shared conversations, briefs, alerts, tenant API, private packages | Driven by client demand |

---

## 12. Open questions for scoping

Answers to these change the design materially. Where a provisional assumption is made, it is stated.

**Clients and use case**

1. Who are the first tenants and roughly how many users each? (Assumed: 5–20 tenants, 5–50 users each in year one.) This drives IdP choice, sizing and whether tenant SSO federation is MVP.
2. What does a typical session look like: quick fact lookup, deep multi-turn research, or producing deliverables (briefs, slides)? This decides how much to invest in history, export and "briefs" features.
3. Do clients expect answers in languages other than English, or sources in multiple languages? This decides the embedding model and whether a multilingual eval set is needed from day one.
4. Will any client bring their own documents later? The compliance guide assumes not; if "later" is likely, the tenant-private dataset path should be designed in now rather than retrofitted.

**Corpus and entitlements**

5. How is the corpus packaged commercially: flat tiers, per-client packages, per-topic subscriptions, or a mix? (Assumed: tiers plus optional client-specific packages.) This fixes the entitlement tag model and dataset layout.
6. Expected corpus size at launch and in 12 months (documents, pages, crawled sites)? This drives host sizing and whether Elasticsearch or Infinity is the better index.
7. For third-party PDFs: do existing licences permit text-and-data mining and showing excerpts to clients? Is there a list we can review now? If most licences prohibit it, the product may need to rely on our own analysis plus permitted sources only.
8. How often does crawled content change, and must answers reflect changes within hours, days or weeks? This sets crawl schedules and re-ingestion cadence.
9. Should users be able to view the full source document in-app, or only the cited excerpt plus a link? Licensing usually decides this per publisher.

**Answer behaviour**

10. How strictly should the assistant abstain? "Only answer from the corpus" is the assumption; some clients prefer the model to add clearly labelled general knowledge.
11. Should answers be able to draw on conversation history across sessions (a tenant-level memory), or is each conversation independent? Memory increases usefulness and privacy surface.
12. Is there a house style for answers (length, structure, tone, mandatory caveats)?

**Compliance and contract**

13. Default chat-history retention: 0, 7 or 30 days, and may tenants extend it? (Assumed: 30 days default, tenant-configurable down to 0, extension only by contract.)
14. Will cross-tenant query data be used for retrieval tuning at all? (Assumed: no, except aggregated, pseudonymised metrics with a minimum group size.)
15. Which providers' ZDR terms are already in hand? Mistral offers zero-retention on request for business customers and Scaleway states no retention on Generative APIs; both need written confirmation naming our organisation, models and endpoints before launch.
16. Is SOC 2 required by the first clients, or is ISO 27001 the more relevant signal in your market? This sets the assurance roadmap in Phase 2.
17. Do any clients require a dedicated instance (separate RAGFlow and database) rather than logical isolation? This is a different hosting tier and price point.

**Identity**

18. Will clients want to log in with their own corporate IdP (Microsoft Entra, Google Workspace, Okta) from day one, or are platform-managed accounts with MFA acceptable for MVP? (Assumed: platform-managed for MVP, federation in Phase 2.)

**Operations and team**

19. Who operates the platform day to day, and what is their comfort with Docker Compose on VPS versus managed Kubernetes? This affects the hosting recommendation.
20. Monthly budget envelope for hosting and LLM usage? This affects model choice (e.g. Mistral Large versus Medium/Small) and whether query rewriting and LLM-judged evaluation are affordable from the start.
21. Which VPS provider is preferred or already in use (Scaleway, Hetzner, OVH, other)? Using Scaleway for both hosting and inference simplifies the vendor list and private networking.

**Product**

22. Is a tenant-facing API (for integration into client tools) in scope for year one?
23. Are there features the first clients have explicitly asked for that are not listed in §7?
