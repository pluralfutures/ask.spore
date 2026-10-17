# Platform Architecture & Functional Design — Multi-Tenant RAG Chatbot

Oct 17, 2026 · Revision 2 (incorporates scoping answers)

Companion to [Compliance & Privacy Design Guide](./Compliance%20%26%20Privacy%20Design%20Guide%20%E2%80%94%20Multi-Tenant%20RAG%20Chatbot%20%28Public%20Sources%20Only%29.md). That document sets the SOC 2, GDPR and ZDR requirements; this one describes the system that satisfies them. Where the two disagree, the compliance guide wins and this document should be amended. One addendum to the compliance guide (web-search mode) was added alongside this revision.

This is a design, not an implementation plan. Scoping decisions are recorded in §12; the few remaining questions are in §13.

---

## 1. Summary

A hosted research assistant. Business clients (tenants) log in, ask questions in a chat interface, and receive cited answers drawn from a curated corpus: licensed third-party PDFs, crawled public web pages and our own DOCX/PPTX analysis. Each tenant sees a client-specific package assembled by us. By default answers come strictly from the corpus; per tenant, we can enable a general-knowledge mode and a web-search mode.

Key decisions:

| Decision | Choice | Rationale |
| --- | --- | --- |
| Retrieval engine | RAGFlow, self-hosted, internal only | Strong document parsing (DeepDoc) for PDF/DOCX/PPTX, built-in chunking, hybrid search, retrieval API with per-dataset scoping |
| Corpus model | One shared RAGFlow instance; one dataset (knowledge base) per content tag; a tenant package is a set of tags | Logical isolation was chosen; packages are composed by us without re-ingesting documents |
| Tenant boundary | Our own application layer, not RAGFlow's tenant model | RAGFlow's users/teams are an admin convenience, not a security boundary we would expose to clients |
| Generation | Our application calls the LLM directly; RAGFlow is used for retrieval only | Full control of prompt contents, ZDR endpoint, region pin, citation format, answer modes, streaming and logging |
| LLM provider | Mistral (La Plateforme, EU) primary; Scaleway Generative APIs (Paris) as second provider and fallback | Both EU-hosted; OpenAI-compatible interfaces; zero-retention confirmations in hand |
| Embeddings | Self-hosted on the retrieval host (RAGFlow bundled model, e.g. bge-m3) | Corpus text never leaves the VPS during ingestion; multilingual |
| Identity | Self-hosted identity broker (Authentik recommended) with Microsoft Entra, Google Workspace, generic OIDC/SAML federation, and emailed sign-in links | All requested login methods in one EU-hosted component; per-tenant login policy |
| Answer modes | Corpus-only (default); General-knowledge; Web-search. Enabled per tenant by the platform operator | Strict grounding by default; modes are explicit, labelled and auditable |
| Source access | Excerpt plus link to the original; no in-app full-document viewer | Licensing-safe by construction; simpler product |
| History retention | 30 days maximum, fixed; tenant admin may shorten to 0 | Decided |
| Hosting | Scaleway (Paris) Instances, Private Network, Object Storage, Transactional Email, Secret Manager | Single EU vendor for hosting, email and fallback inference; low expected load |

---

## 2. Actors and roles

| Actor | Who | What they do |
| --- | --- | --- |
| Tenant user ("analyst") | Client employee | Chat, browse history, view sources, switch answer mode where enabled, give feedback |
| Tenant admin | Client-side lead | Manage their users, shorten history retention, view tenant usage and audit log |
| Platform operator | Our team | Create tenants, build packages, assign entitlements, enable answer modes, configure tenant SSO, time-boxed support access |
| Content editor | Our research team | Add sources to the register, upload analysis, run crawls, approve ingestion, process takedowns |
| Content reviewer | Our research lead | Approve licence basis, publish sources to tags |
| Platform security | Our security lead | Review audit logs and alerts, run evaluations, manage keys and vendors |

Tenant-side roles are enforced by our application. Operator-side roles are enforced in the admin console and mapped to RAGFlow service credentials that clients never see.

---

## 3. Logical architecture

```mermaid
flowchart LR
  subgraph Client
    B[Browser]
    EIDP[Client IdP\nEntra / Google / OIDC / SAML]
  end

  subgraph Scaleway Paris — Application host
    RP[Reverse proxy / TLS\nCaddy or Traefik]
    WEB[Chat web app]
    API[Platform API\nauth, tenancy, packages,\nanswer modes, orchestration, audit]
    IDP[Identity broker\nAuthentik]
    PG[(PostgreSQL\ntenants, users, chats,\nsource register, audit)]
    RD[(Redis\nsessions, rate limits,\ntenant-keyed cache)]
    WRK[Workers\ncrawler, ingestion,\nretention, eval, web-fetch]
  end

  subgraph Scaleway Paris — Retrieval host (Private Network only)
    RF[RAGFlow server\nparsing, chunking,\nhybrid retrieval API]
    ES[(Elasticsearch / Infinity\nindex)]
    MIO[(MinIO\noriginal files)]
    MY[(MySQL\nRAGFlow metadata)]
    EMB[Embedding model\nself-hosted]
  end

  subgraph EU providers
    MIS[Mistral La Plateforme\nEU, ZDR]
    SCW[Scaleway Generative APIs\nParis, no retention]
    TEM[Scaleway Transactional Email\nsign-in links]
    WS[Web search provider\nweb-search mode only]
  end

  OBJ[(Scaleway Object Storage\nencrypted backups)]

  B -- HTTPS --> RP --> WEB
  WEB --> API
  API <--> IDP
  IDP <-- federation --> EIDP
  IDP --> TEM
  API <--> PG
  API <--> RD
  API -- retrieval only\n(dataset IDs injected) --> RF
  API -- query + chunks + system prompt --> MIS
  API -. fallback .-> SCW
  WRK -. web-search mode .-> WS
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

- **Clients only ever talk to the reverse proxy.** RAGFlow, its databases and MinIO sit on the Scaleway Private Network with no public listener.
- **The platform API is the only RAGFlow client.** It holds one RAGFlow service API key per environment. Tenant identity never reaches RAGFlow; only the list of dataset IDs in the tenant's package.
- **Outbound calls carrying query data**: the generation request to the LLM provider in every mode, and the search request to the web-search provider in web-search mode only. Everything else stays on the two hosts.

---

## 4. Components

### 4.1 Chat web app

Single-page app served from the application host. Responsibilities: login via the identity broker, chat UI with streaming, mode selector (when more than one mode is enabled), citation panel, history, tenant admin pages. No business logic; no direct calls to RAGFlow, the LLM or the search provider.

### 4.2 Platform API

The heart of the system. Owns:

- **Authentication**: validates OIDC tokens from the identity broker, resolves user → tenant → roles.
- **Tenancy and packages**: tenant record, package (set of content tags → dataset IDs), enabled answer modes, retention setting, login policy.
- **Chat orchestration** (§5): query rewriting, retrieval, optional web search, prompt assembly, LLM call, citation mapping, streaming, persistence.
- **Guardrails**: per-user and per-tenant rate limits, bulk-extraction detection, output scanning.
- **Audit log** writer (§8).
- **Admin and content-ops APIs** consumed by the console.

Suggested stack: a typed backend (TypeScript/NestJS or Python/FastAPI), PostgreSQL with row-level security on all tenant-scoped tables, Redis for sessions and limits.

### 4.3 Identity broker

Self-hosted **Authentik** on the application host (Keycloak with the magic-link extension, or Zitadel, are workable alternatives; Authentik is recommended because emailed sign-in links, OIDC/SAML federation and per-tenant branding are native).

Login methods, all terminating at the broker so the application sees one OIDC issuer:

| Method | How | Notes |
| --- | --- | --- |
| Microsoft Entra ID | OIDC federation, one source per tenant | Tenant's Entra tenant ID pinned; group claims optionally mapped to roles |
| Google Workspace | OIDC federation, hosted-domain restricted per tenant | `hd` claim checked |
| Generic SSO | OIDC or SAML 2.0 source per tenant | Covers Okta, Ping, JumpCloud, Keycloak and others |
| Emailed sign-in link | Email-link stage via Scaleway Transactional Email | Single-use, 15-minute expiry, bound to the requesting browser; rate-limited per address |

Policy:

- **Tenant discovery by email domain**: the login page asks for an email address; the domain maps to a tenant and to that tenant's allowed methods. A user is only ever created inside their tenant; a domain can belong to one tenant.
- **Per-tenant login policy** set by the operator: which methods are allowed, whether sign-in links are permitted for all users or only as a fallback, session lifetime.
- **Tenant admins** must use SSO or sign-in link plus a second factor (TOTP or passkey). Platform operators use a separate internal tenant with hardware-key MFA.
- **Just-in-time provisioning** from SSO is allowed only for domains the operator has verified; otherwise users are invited by the tenant admin.
- Login, logout, failed login, link issuance and admin events are forwarded to the audit log.

### 4.4 RAGFlow (retrieval tier)

Deployed from the official Docker Compose on the retrieval host. Used for:

- **Parsing**: DeepDoc for PDF (layout, tables, figures with captions), native DOCX and PPTX parsing, HTML/Markdown for crawled pages.
- **Chunking**: per-dataset chunking method ("paper" or "book" for reports, "presentation" for PPTX, "naive" for web pages); chunk size and overlap tuned per source type.
- **Indexing**: hybrid dense + full-text index in Elasticsearch (default) or Infinity.
- **Retrieval**: the HTTP retrieval endpoint, called with a list of dataset IDs, the query, `top_k`, similarity threshold and optional keyword re-ranking.

Not used for: end-user authentication, chat history, the client-facing chat assistant, or anything exposed to clients. The RAGFlow web UI is reachable only over the Private Network and only by content and platform roles.

**Dataset layout.** One RAGFlow dataset per **content tag**. Tags are the unit of packaging: topic or publisher collections (`src-<publisher>`, `topic-<area>`), our analysis collections (`analysis-<series>`), and client-specific collections (`client-<slug>`) for analysis produced for one client. A document that belongs in several tags is linked into each dataset; the source register records the mapping. A **tenant package** is a set of tags assembled by the operator; the API resolves it to dataset IDs at query time and never accepts dataset IDs from the client.

### 4.5 Workers

Background processes on the application host:

- **Crawler**: scheduled crawls of registered sites. Honours robots.txt and the EU text-and-data-mining opt-out signals, respects crawl delay, stores raw HTML plus a cleaned Markdown rendering, records fetch date and hash. Candidate tooling: Crawl4AI or Scrapy with a readability pass. Produces files that are then uploaded to the right RAGFlow dataset.
- **Ingestion**: moves approved source-register entries into RAGFlow (upload, trigger parse, poll status), records chunk counts and parse errors back in the register.
- **Web-fetch** (web-search mode only): calls the search provider, fetches the top result pages server-side, strips boilerplate, and returns text snippets to the orchestrator. Nothing fetched is written to the corpus or persisted beyond the chat record's citation list.
- **Retention**: nightly job applying the chat-history TTL per tenant, log retention, cache expiry, and the source-level delete cascade for takedowns.
- **Evaluation**: runs the versioned eval set against the current retrieval and prompt configuration on every change (§9).

### 4.6 Data stores

| Store | Content | Tenant scoping |
| --- | --- | --- |
| PostgreSQL (app) | Tenants, users, roles, packages, login policy, conversations, messages, citation sets, feedback, source register, audit log, usage aggregates | Row-level security keyed on `tenant_id`; audit and source register are operator-only |
| Redis | Sessions, rate-limit counters, semantic/answer cache | Every cache key prefixed with `tenant_id`; cache keyed additionally on answer mode |
| RAGFlow (MySQL, ES/Infinity, MinIO) | Corpus only: files, parsed text, chunks, embeddings | Not tenant-scoped; scoped by dataset = content tag |
| Scaleway Object Storage | Encrypted nightly backups of PostgreSQL, MinIO and index snapshots | Per-tenant purge of history tested quarterly |

---

## 5. Query pipeline

### 5.1 Answer modes

| Mode | Sources the model may use | Who enables it | UI labelling |
| --- | --- | --- | --- |
| **Corpus-only** (default) | Retrieved chunks from the tenant's package only; abstains otherwise | Always on | "Answered from your research package" |
| **General knowledge** | Retrieved chunks, plus the model's own knowledge where the corpus is silent or incomplete | Operator, per tenant | Corpus-backed statements carry citations; uncited sentences are rendered in a distinct style and the answer carries a "includes general knowledge, not from your package" banner |
| **Web search** | Retrieved chunks, plus live web results fetched server-side | Operator, per tenant | Web citations are shown separately from corpus citations with the fetched URL and date; banner states that the query was sent to a web search provider |

When more than one mode is enabled, the user picks the mode per conversation; the tenant admin sets the default. The mode is stored on every message and in the audit event. Corpus citations always take precedence in the prompt ordering so that licensed research is never displaced by web text.

### 5.2 Request flow

1. **Auth and context**: API validates the token, loads tenant, user, roles, package dataset IDs, enabled modes, retention and feature flags.
2. **Guardrails in**: rate limit check (user, tenant), input length cap, bulk-extraction heuristics (query cadence, near-duplicate queries, pagination-like patterns).
3. **Conversation context**: load the last N turns of this conversation (bounded by tokens).
4. **Query rewriting** (small EU model): turn a follow-up such as "and in Germany?" into a standalone retrieval query using the conversation context.
5. **Retrieval**: call RAGFlow retrieval with the package's dataset IDs, rewritten query, `top_k` (8–12 after re-ranking), similarity threshold. User-selected filters (publisher, date range, source type, tag) are applied as RAGFlow document filters or post-retrieval using register metadata.
6. **Web search** (web-search mode only): the web-fetch worker runs the rewritten query against the search provider, fetches the top 3–5 pages, extracts text, and returns snippets with URL and fetch time. Snippets are wrapped as untrusted content.
7. **Chunk selection**: de-duplicate overlapping chunks, cap total context tokens (corpus first, then web), attach provenance (publisher, title, date, tag, source ID, page/slide, or URL) to every chunk.
8. **Prompt assembly**: mode-specific system prompt, numbered context chunks, conversation turns, user query. No tenant name, user identifier or package information in the prompt. Corpus-only prompt forbids outside knowledge; general-knowledge prompt requires outside-knowledge sentences to be marked; web prompt requires web claims to cite a web chunk.
9. **Generation**: streamed call to the primary EU provider; automatic failover to the secondary on 5xx/timeouts. Model version pinned in configuration.
10. **Guardrails out**: scan the stream for system-prompt leakage and for strings matching other tenants' identifiers; truncate on bulk-reproduction patterns (very long verbatim spans from a single licensed source).
11. **Citation mapping**: map `[n]` markers to the chunk set, split into corpus and web citations; drop markers that reference nothing; in corpus-only mode flag answers with no citations as "unsupported".
12. **Persist**: message, answer, mode, citation set (source IDs + chunk IDs + offsets, or URLs for web), token counts, latency, model version. Write audit event.
13. **Cache**: store answer keyed by `tenant_id + mode + normalised query + package hash + corpus version`; short TTL; web-search answers are not cached.

### 5.3 Abstention and honesty

In corpus-only mode the system prompt instructs the model to answer only from supplied chunks and to say when the corpus does not cover the question. Retrieval results below the similarity threshold yield a "nothing relevant found in your package" response without calling the LLM, with a suggestion to switch mode if another mode is enabled for the tenant.

### 5.4 Why generation sits in our API, not in RAGFlow chat assistants

RAGFlow can host "chat assistants" bound to datasets and call the LLM itself. We own generation in the platform API because:

- We control exactly what leaves the VPS (data minimisation at the model boundary is a compliance control).
- We control the provider, endpoint region, failover and model pinning in one place.
- Answer modes, citations, streaming format and abstention behaviour are ours to test and version.
- Chat history lives in our tenant-scoped PostgreSQL, not RAGFlow's MySQL.

Phase 0 may use a RAGFlow chat assistant behind our API for an early demo; it cannot support the answer modes or the labelling rules above and must be replaced before the first tenant.

---

## 6. Content pipeline

### 6.1 Source register

PostgreSQL table, the single source of truth for what is in the corpus and why. Fields: source ID, type (PDF, web, DOCX, PPTX), URL or file hash, publisher, title, publication date, canonical link shown to users, licence basis (licence name, permission letter reference, or "own work"), content tags, crawl/upload date, review date, status (proposed, approved, ingested, withdrawn), RAGFlow document IDs per dataset, takedown reference if any.

No document reaches RAGFlow without an approved register row. This is both the licensing defence and the index for erasure. Licences are assumed to permit text-and-data mining and excerpt display; the register still records the basis per document so that an exception can be handled.

### 6.2 Ingestion flows

| Source type | Flow |
| --- | --- |
| Third-party PDF | Editor uploads to the register with licence basis and canonical link → reviewer approves → worker uploads to the tagged datasets → RAGFlow parses (DeepDoc, "paper"/"book" method) → chunk count and errors recorded → spot-check in the RAGFlow UI → status "ingested" |
| Crawled website | Editor registers the site, scope rules and crawl schedule → worker checks robots.txt and TDM opt-out, crawls, renders Markdown, computes hashes → changed pages are re-ingested, removed pages are withdrawn → register updated per page; the page URL is the canonical link |
| Own analysis (DOCX/PPTX) | Editor uploads with target tags → ingested with "naive"/"presentation" method → optional metadata (project, client package) attached; canonical link is an operator-chosen location (shared drive link or none) |

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
- **Answer mode selector** shown only when the tenant has more than one mode enabled; mode banner on every answer.
- **Citations**: numbered inline markers; side panel listing sources with publisher, title, date, page/slide and the exact excerpt used; a link to the original at its canonical location. Web citations (web-search mode) listed separately with URL and fetch time. No in-app full-document viewer.
- **Conversation history**: list, search by title, rename, delete (hard delete, immediate), export a single conversation as PDF/Markdown with citations. Expiry date shown on each conversation.
- **Follow-up questions** and suggested questions generated from the retrieved sources.
- **Source filters**: restrict a query to publishers, date range, source type or a tag within the package.
- **Feedback**: thumbs up/down with optional comment per answer; feeds the eval set after review.
- **Transparency**: a persistent "AI-generated, verify against cited sources" notice; a package page listing which collections the tenant can query and when each was last updated.

### 7.2 Tenant admin features (MVP)

- Invite, deactivate and role-assign users; see last login and login method.
- Shorten chat-history retention from the 30-day maximum (down to 0); the maximum cannot be raised.
- Set the default answer mode among those the operator enabled.
- Usage dashboard: queries per day by mode, active users, top sources (no query text).
- Download tenant audit log (auth and admin events).
- View the tenant's configured SSO connection (configuration itself is done by the operator with the client's IT contact).

### 7.3 Content operations console (MVP)

- Source register CRUD with approval workflow, licence file attachment and canonical link.
- Crawl management: register sites, scope, schedule; see last crawl, page counts, blocked pages and why.
- Ingestion status per source, parse errors, chunk previews (via link into the private RAGFlow UI).
- Takedown queue with SLA timer.
- Tag management and the tag-to-dataset mapping.

### 7.4 Platform operator console (MVP)

- Tenant lifecycle: create, suspend, terminate (triggers purge cascade with certificate of deletion for history and account data).
- **Package builder**: compose a tenant's package from tags, preview document counts, publish; package changes are versioned and audited.
- **Answer modes** per tenant: enable General knowledge and Web search; record the contractual basis (DPA clause reference) when enabling web search.
- **Login policy** per tenant: allowed methods, verified email domains, SSO source configuration (Entra tenant ID, Google hosted domain, OIDC/SAML metadata), MFA requirement for admins.
- Cross-tenant aggregates only: query volumes by mode, latency, cost per provider, error rates. No per-tenant query text.
- Vendor and model configuration: provider endpoints, model pins, failover order, search provider, prompt template versions.
- Evaluation results and regression gate status.
- Support access: time-boxed "view tenant settings" mode without impersonation; any access is logged and visible to the tenant.

### 7.5 Later-phase features (not MVP)

- Shared conversations and annotations within a tenant.
- Saved "briefs": pinned answers assembled into a document.
- Alerting: notify a tenant when new sources matching a saved query are ingested.
- Tenant self-service SSO configuration.
- API access for tenants to integrate into their own tools, with the same package enforcement.
- Dedicated instances, only if a future contract demands it (not planned).

---

## 8. Security and isolation controls (implementation view)

This section states how the compliance guide's controls are realised; it does not restate why.

| Control | Realisation |
| --- | --- |
| Package enforcement | Dataset IDs resolved server-side from the package table; the retrieval call is built by the API only. CI test: a fixture tenant with package A issues queries known to match only package-B documents and must receive nothing |
| Query and history isolation | PostgreSQL row-level security on every tenant table; the API sets `tenant_id` per transaction from the token, never from request parameters. Integration test asserts cross-tenant reads return zero rows |
| Cache isolation | Redis keys prefixed by tenant and mode; a lint rule rejects cache calls without the tenant prefix helper |
| Data minimisation at the model boundary | One prompt-builder module per mode; templates under version control; unit test asserts no tenant/user identifiers appear in the serialised request |
| Web-search boundary | Search calls only from the web-fetch worker, only for tenants with the mode enabled, only with the rewritten query (never conversation history or chunks); provider pinned in configuration; every call audited |
| Region and ZDR pin | Provider base URLs and model names in configuration with an allow-list; startup check refuses non-EU endpoints; ZDR letter references stored next to the configuration |
| Encryption | TLS 1.2+ at the proxy; Scaleway Private Network between hosts, WireGuard if a host ever sits outside it; encrypted volumes; backups encrypted with a key held in Scaleway Secret Manager |
| Metadata-only logs | Structured logging with an explicit allow-list of fields; request and response bodies never logged; linter rule and code-review checklist item |
| Rate limits and extraction detection | Redis token buckets per user and tenant (defaults sized well above 15 queries per user per day); anomaly rules (queries per minute, verbatim overlap of outputs with a single source, sequential pagination-like queries) raise alerts and apply temporary throttling |
| Prompt-injection resistance | Retrieval is read-only; no tools; crawled and web-fetched text is wrapped as untrusted context; output scanner for system-prompt leakage |
| Sign-in link hardening | Single-use tokens, 15-minute expiry, bound to the browser that requested them, per-address and per-IP rate limits, no account enumeration in responses |
| Audit log | Append-only table plus daily export to write-once object storage; events: auth (with method), admin actions, package changes, mode changes, source-register changes, takedowns, support access, every query (mode, metadata and cited chunk IDs or URLs, not text) |
| Secrets | Provider API keys, RAGFlow service key, SMTP and database credentials in Scaleway Secret Manager; rotated on schedule and on staff departure |
| Hardening | Both hosts: SSH keys only, Scaleway security groups default-deny, automatic security updates, fail2ban, container images pinned by digest, weekly vulnerability scan, annual pentest |

---

## 9. Quality, evaluation and observability

- **Eval set**: 100–300 question/answer pairs with expected source IDs, built from our own analysis and licensed sources, plus a set of out-of-corpus questions to test abstention. Versioned in the repo. Metrics: retrieval hit rate at k, citation precision, answer faithfulness (LLM-judged against the chunks, using the EU provider), abstention correctness per mode.
- **Regression gate**: eval runs on every change to chunking, embedding model, prompt templates, retrieval parameters or LLM model version; a drop beyond a threshold blocks deployment.
- **Observability**: metrics (latency per stage, tokens, provider errors, cache hit rate, mode usage), traces per request with tenant ID only, alerts on error rate and on guardrail triggers. All telemetry stays on the VPS (Prometheus/Grafana/Loki or equivalent); no SaaS APM that receives bodies.
- **Cost tracking**: tokens per tenant per day, per provider and mode, with budget alerts.

---

## 10. Deployment, sizing and cost

### 10.1 Topology on Scaleway

- **Region**: Paris (fr-par) for Instances, Private Network, Object Storage, Transactional Email, Secret Manager and Generative APIs.
- **Environments**: dev (local Compose), staging (one small Instance), production (two Instances). Staging uses synthetic queries and a subset corpus; never real client history.
- **Application host**: proxy, web, API, Authentik, PostgreSQL, Redis, workers, monitoring.
- **Retrieval host**: RAGFlow stack with Elasticsearch, MySQL, MinIO, Redis and the embedding model.
- **Networking**: Private Network between hosts; public ingress only on 443 on the application host via a security group; RAGFlow has no public IP.
- **Backups**: nightly encrypted dumps of PostgreSQL and RAGFlow stores to Object Storage with object lock; weekly restore test; per-tenant purge procedure documented and tested.
- **Upgrades**: RAGFlow pinned to a tested version; upgrade on staging with the eval gate before production.
- **Incident response**: runbooks for provider outage (failover), index corruption (restore from snapshot), suspected cross-tenant leak (freeze, investigate from audit log, notify per DPA window).
- **Capacity path**: if load outgrows the two hosts, the same containers move to Scaleway Kubernetes Kapsule; RAGFlow supports Helm deployment.

### 10.2 Load assumptions

Per tenant: 10 users, 15 queries each per day → 150 queries per tenant per day. The design is sized for 20 tenants.

| Metric | Value |
| --- | --- |
| Queries per day at 20 tenants | 3,000 |
| Average rate over a 10-hour working day | ~5 per minute |
| Planning peak | 30 per minute |
| LLM calls per query (rewrite + answer) | 2 |
| Context tokens per answer call (typical) | 6,000 in, 500 out |

This is light load. The retrieval host is sized by RAGFlow's baseline needs (parsing and the index), not by query volume; the application host is sized by Authentik and PostgreSQL headroom.

### 10.3 Indicative sizing and monthly cost (to be confirmed against current Scaleway and provider price lists)

| Item | Spec | Estimate |
| --- | --- | --- |
| Retrieval host | 8 vCPU, 32 GB RAM, 200 GB block storage (RAGFlow + Elasticsearch + embedding model) | ~€150 |
| Application host | 4 vCPU, 16 GB RAM, 100 GB block storage | ~€70 |
| Staging host | 4 vCPU, 16 GB RAM, used intermittently | ~€40 |
| Object Storage backups | ~200 GB | ~€5 |
| Transactional Email | a few thousand sign-in links per month | ~€0–10 |
| LLM usage, Mistral Medium class | 3,000 queries/day × ~7k tokens | ~€150–250 |
| LLM usage, Mistral Large class (if chosen) | same volume | ~€400–600 |
| Web search provider (if enabled for some tenants) | per-query pricing | depends on provider and share of web-mode queries |

Order of magnitude: €450–600 per month for infrastructure plus mid-tier inference at 20 tenants, before monitoring extras and the annual pentest. Costs scale almost linearly with query volume on the LLM line only.

---

## 11. Phasing

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| 0 — Proof of value (4–6 weeks) | RAGFlow on one Scaleway Instance, a sample corpus, a thin login (sign-in link only) and chat UI, Mistral EU endpoint, corpus-only mode | Internal team and one friendly client get cited answers; eval set v1 exists |
| 1 — MVP (8–12 weeks) | Platform API with tenancy, packages, own generation path, corpus-only and general-knowledge modes, history with 30-day cap, excerpt-plus-link citations, content console, source register, audit log, retention jobs, Authentik with Entra, Google, OIDC/SAML and sign-in links, two-host deployment | Compliance guide's "before first client login" checklist complete; first paying tenants |
| 2 — Scale and assurance | Web-search mode with its DPA clause and UI labelling, tenant admin dashboard, extraction detection tuning, provider failover drills, trust page; SOC 2 observation window starts | SOC 2 Type I; three or more tenants |
| 3 — Depth | Shared conversations, briefs, alerts, tenant self-service SSO, tenant API | Driven by client demand |

Web-search mode is placed in Phase 2 because it adds a sub-processor, a DPA clause and new UI labelling; it can be pulled into Phase 1 if a launch client requires it.

---

## 12. Decisions log (from scoping)

| Topic | Decision |
| --- | --- |
| Login methods | Microsoft Entra ID, Google Workspace, generic OIDC/SAML SSO, and emailed sign-in links; realised through a self-hosted identity broker |
| Packaging | Client-specific packages composed by the platform operator from content tags; no self-service purchase |
| Licensing | Third-party licences assumed to permit text-and-data mining and excerpt display; register still records basis per document |
| Source access | Excerpt plus link to the original; no in-app full-document viewer |
| Answer modes | Corpus-only by default; operator may enable General knowledge and Web search per tenant |
| History retention | 30 days maximum, fixed; tenant admin may shorten |
| ZDR | Written zero-retention confirmations from Mistral and Scaleway are in hand |
| Assurance | SOC 2 (Security and Confidentiality); ISO 27001 not pursued now |
| Isolation | Logical isolation on a shared platform; no dedicated instances |
| Hosting | Scaleway, Paris; low load (10 users × 15 queries/day per tenant) |

---

## 13. Remaining questions

These are second-order and do not block Phase 0 or most of Phase 1.

1. **Web search provider.** The query text leaves our control in this mode, so the provider must be EU-hosted or covered by a DPA with transfer safeguards. Candidates to evaluate: Mistral's built-in web-search tool (EU, same DPA), a self-hosted meta-search engine (queries still reach upstream engines), or a commercial search API under SCCs. Which trade-off do you prefer: fewest vendors (Mistral tool) or best result quality?
2. **Who may enable modes.** The design gives the operator the switch and the tenant admin the default. Should tenant admins be allowed to enable General knowledge themselves, with only Web search gated by us?
3. **Own-analysis links.** For DOCX/PPTX we produce, is the "link to the original" a download from our platform, a shared-drive link, or nothing beyond the excerpt?
4. **Sign-in links for all users.** Allowed for every tenant by default, or only where the client has no SSO? Some client IT departments ask that sign-in links be disabled once SSO is live.
5. **Model tier.** Mistral Medium class is sufficient for cited Q&A and halves inference cost against Large; confirm Medium as the default with Large available per tenant if needed.
