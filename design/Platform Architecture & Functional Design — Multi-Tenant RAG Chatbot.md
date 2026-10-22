# Platform Architecture & Functional Design — Multi-Tenant RAG Chatbot

Oct 17, 2026 · Revision 3 (scoping complete) · §15 added Oct 22, 2026 (client-supplied documents, DRAFT for owner and counsel review)

Companion to [Compliance & Privacy Design Guide](./Compliance%20%26%20Privacy%20Design%20Guide%20%E2%80%94%20Multi-Tenant%20RAG%20Chatbot%20%28Public%20Sources%20Only%29.md). That document sets the SOC 2, GDPR and ZDR requirements; this one describes the system that satisfies them. Where the two disagree, the compliance guide wins and this document should be amended. One addendum to the compliance guide (web-search mode) was added alongside this revision.

This is a design, not an implementation plan. Scoping decisions are recorded in §12. No questions remain open; §13 lists assumptions still to be verified during Phase 0.

---

## 1. Summary

A hosted research assistant. Business clients (tenants) log in, ask questions in a chat interface, and receive cited answers drawn from a curated corpus: licensed third-party PDFs, crawled public web pages and our own DOCX/PPTX analysis. Each tenant sees a client-specific package assembled by us. By default answers come strictly from the corpus; per tenant, we can enable a general-knowledge mode and a web-search mode.

Key decisions:

| Decision | Choice | Rationale |
| --- | --- | --- |
| Retrieval engine | RAGFlow, self-hosted, internal only | Strong document parsing (DeepDoc) for PDF/DOCX/PPTX, built-in chunking, hybrid search, retrieval API with per-dataset scoping |
| Corpus model | One shared RAGFlow instance; one dataset (knowledge base) per content tag; a tenant package is a set of tags | Logical isolation was chosen; packages are composed by us without re-ingesting documents. *DRAFT, Oct 22, 2026 (§15.4):* every tag now belongs to one tenant and is never shared across tenants; content needed by two tenants is ingested into each tenant's own tags |
| Tenant boundary | Our own application layer, not RAGFlow's tenant model | RAGFlow's users/teams are an admin convenience, not a security boundary we would expose to clients |
| Generation | Our application calls the LLM directly; RAGFlow is used for retrieval only | Full control of prompt contents, ZDR endpoint, region pin, citation format, answer modes, streaming and logging |
| LLM provider and model | Mistral (La Plateforme, EU) primary, Mistral Large class pinned by default; Scaleway Generative APIs (Paris) as fallback with the closest available Mistral model | Both EU-hosted; zero-retention confirmations in hand; Large chosen for answer quality on long research contexts |
| Web search | Mistral's built-in web-search tool, called through the same EU endpoint and DPA | Fewest vendors; query text stays with a sub-processor already under contract |
| Embeddings | Self-hosted on the retrieval host (RAGFlow bundled model, e.g. bge-m3) | Corpus text never leaves the VPS during ingestion; multilingual |
| Identity | Self-hosted identity broker (Authentik recommended) with Microsoft Entra, Google Workspace, generic OIDC/SAML federation, and emailed sign-in links (on by default, operator can disable per tenant) | All requested login methods in one EU-hosted component; per-tenant login policy |
| Answer modes | Corpus-only (default); General-knowledge; Web-search. Enabled per tenant by the platform operator only; tenant admins cannot enable modes | Strict grounding by default; modes are explicit, contractual, labelled and auditable |
| Source access | Excerpt plus link: third-party sources link to the publisher's canonical location; our own DOCX/PPTX analysis is downloadable from the platform | Licensing-safe for third-party content; our own work is ours to distribute |
| History retention | 30 days maximum, fixed; tenant admin may shorten to 0 | Decided |
| Hosting | Scaleway (Paris) Instances, Private Network, Object Storage, Secret Manager | Single EU vendor for hosting and fallback inference; low expected load |
| Email | Scaleway Transactional Email, fr-par, primary; Mailgun EU region optional backup (revised Oct 20, 2026; Mailgun alone from Oct 19 to Oct 20) | Sign-in links and the API's own transactional mail through one active provider; HTTP API for the API, SMTP relay for Authentik's email stage; the primary sits under the Scaleway DPA already on file, the backup needs its own DPA and SCCs before activation (compliance guide, Oct 20 update) |

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
    TEM[Scaleway Transactional Email\nfr-par, sign-in links\n(Mailgun EU as backup)]
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
  API -. web-search mode:\nMistral web-search tool .-> MIS
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
- **Outbound calls carrying query data**: the generation request to the LLM provider in every mode; in web-search mode the same provider's web-search tool is invoked within that request. No other third party receives query text. Everything else stays on the two hosts.

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
| Emailed sign-in link | Email-link stage via Scaleway Transactional Email (fr-par, SMTP relay; Mailgun EU as optional backup) | Single-use, 15-minute expiry, bound to the requesting browser; rate-limited per address |

Policy:

- **Tenant discovery by email domain**: the login page asks for an email address; the domain maps to a tenant and to that tenant's allowed methods. A user is only ever created inside their tenant; a domain can belong to one tenant.
- **Per-tenant login policy** set by the operator: which SSO sources are configured, whether emailed sign-in links are enabled (on by default for every tenant; the operator switches them off per tenant, typically once a client's SSO is live and their IT asks for it), session lifetime.
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

*DRAFT, Oct 22, 2026:* every tag gains an owning tenant and may sit only in that tenant's workspaces; no tag, and so no dataset, is shared across tenants, for platform-gathered and client-supplied content alike. Cross-tenant topic or publisher collections are replaced by per-tenant tags (`<tenant-slug>-<topic>`, as `cc` already does). See §15.4.

### 4.5 Workers

Background processes on the application host:

- **Crawler**: scheduled crawls of registered sites. Honours robots.txt and the EU text-and-data-mining opt-out signals, respects crawl delay, stores raw HTML plus a cleaned Markdown rendering, records fetch date and hash. Candidate tooling: Crawl4AI or Scrapy with a readability pass. Produces files that are then uploaded to the right RAGFlow dataset.
- **Ingestion**: moves approved source-register entries into RAGFlow (upload, trigger parse, poll status), records chunk counts and parse errors back in the register.
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
| **Web search** | Retrieved chunks, plus live web results returned by Mistral's web-search tool | Operator, per tenant | Web citations are shown separately from corpus citations with URL and retrieval date; banner states that the query was used for a live web search |

Modes are enabled only by the platform operator, per tenant, against a contractual basis; tenant admins cannot enable or disable them. When more than one mode is enabled, the user picks the mode per conversation and the tenant admin sets the default. The mode is stored on every message and in the audit event. Corpus citations always take precedence in the prompt ordering so that licensed research is never displaced by web text.

### 5.2 Request flow

1. **Auth and context**: API validates the token, loads tenant, user, roles, package dataset IDs, enabled modes, retention and feature flags.
2. **Guardrails in**: rate limit check (user, tenant), input length cap, bulk-extraction heuristics (query cadence, near-duplicate queries, pagination-like patterns).
3. **Conversation context**: load the last N turns of this conversation (bounded by tokens).
4. **Query rewriting** (small EU model): turn a follow-up such as "and in Germany?" into a standalone retrieval query using the conversation context.
5. **Retrieval**: call RAGFlow retrieval with the package's dataset IDs, rewritten query, `top_k` (8–12 after re-ranking), similarity threshold. User-selected filters (publisher, date range, source type, tag) are applied as RAGFlow document filters or post-retrieval using register metadata.
6. **Web search** (web-search mode only): the generation request to Mistral includes the web-search tool, scoped to the rewritten query. The tool's results (URL, title, snippet, retrieval date) come back as part of the response and are mapped to web citations. Returned web text is treated as untrusted content; the prompt instructs the model to cite web claims to a web result and never to let web content override corpus citations.
7. **Chunk selection**: de-duplicate overlapping chunks, cap total context tokens, attach provenance (publisher, title, date, tag, source ID, page/slide) to every chunk.
8. **Prompt assembly**: mode-specific system prompt, numbered context chunks, conversation turns, user query. No tenant name, user identifier or package information in the prompt. Corpus-only prompt forbids outside knowledge; general-knowledge prompt requires outside-knowledge sentences to be marked; web prompt requires web claims to cite a web chunk.
9. **Generation**: streamed call to Mistral Large (pinned version) on the EU endpoint; automatic failover to the Scaleway endpoint on 5xx/timeouts. Web-search mode does not fail over, because the fallback provider has no equivalent tool; the user is told to retry or switch mode.
10. **Guardrails out**: scan the stream for system-prompt leakage and for strings matching other tenants' identifiers; truncate on bulk-reproduction patterns (very long verbatim spans from a single licensed source).
11. **Citation mapping**: map `[n]` markers to the chunk set, split into corpus and web citations; drop markers that reference nothing; in corpus-only mode flag answers with no citations as "unsupported", and do not show them: the streamed text is held back until it cites a passage, and an answer that never does is replaced by a fixed "no answer from your sources" reply, neither stored nor cached (owner decision Oct 21, 2026, Phase 1a findings G6). General-knowledge answers stream unchanged, since their uncited sentences are the general-knowledge part.
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

PostgreSQL table, the single source of truth for what is in the corpus and why. Fields: source ID, type (PDF, web, DOCX, PPTX), URL or file hash, publisher, title, publication date, canonical link shown to users, licence basis (licence name, permission letter reference, or "own work"), content tags, crawl/upload date, review date, status (proposed, approved, ingested, withdrawn; plus failed, retryable, and rejected, Phase 1b findings A1-1), RAGFlow document IDs per dataset, takedown reference if any.

No document reaches RAGFlow without an approved register row. This is both the licensing defence and the index for erasure. Licences are assumed to permit text-and-data mining and excerpt display; the register still records the basis per document so that an exception can be handled.

*DRAFT, Oct 22, 2026:* a second content model, files chosen and supplied by a client for its own workspaces, adds the licence basis `client-supplied` with the supplying tenant recorded; see §15. The `cc` test client uses only the platform-gathered model described here.

### 6.2 Ingestion flows

| Source type | Flow |
| --- | --- |
| Third-party PDF | Editor uploads to the register with licence basis and canonical link → reviewer approves → worker uploads to the tagged datasets → RAGFlow parses (DeepDoc, "paper"/"book" method) → chunk count and errors recorded → spot-check in the RAGFlow UI → status "ingested" |
| Crawled website | Editor registers the site, scope rules and crawl schedule → worker checks robots.txt and TDM opt-out, crawls, renders Markdown, computes hashes → changed pages are re-ingested, removed pages are withdrawn → register updated per page; the page URL is the canonical link |
| Own analysis (DOCX/PPTX) | Editor uploads with target tags → ingested with "naive"/"presentation" method → optional metadata (project, client package) attached; the original file is kept in platform storage and served as a download link to users whose package includes the tag |

Re-ingestion is versioned: a new parse creates new chunk IDs, old chunks are withdrawn, stored citations keep pointing at the old chunk ID and are shown as "superseded" in the UI. A re-ingestion is a file with new content at the canonical link of exactly one ingested source; the old source is then withdrawn as in §6.3, its citations flagged superseded rather than withdrawn (Phase 1b findings A1-14).

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
- **Citations**: numbered inline markers; side panel listing sources with publisher, title, date, page/slide and the exact excerpt used. Third-party sources link to the publisher's canonical location; our own analysis offers a download of the original DOCX/PPTX from the platform (download is audited and rate-limited). Web citations (web-search mode) listed separately with URL and retrieval date. No in-app full-document viewer.
- **Conversation history**: list, search by title, rename, delete (hard delete, immediate), export a single conversation as PDF/Markdown with citations. Expiry date shown on each conversation.
- **Follow-up questions** and suggested questions generated from the retrieved sources.
- **Source filters**: restrict a query to publishers, date range, source type or a tag within the package.
- **Feedback**: thumbs up/down with optional comment per answer; feeds the eval set after review.
- **Transparency**: a persistent "AI-generated, verify against cited sources" notice; a package page listing which collections the tenant can query and when each was last updated.

### 7.2 Tenant admin features (MVP)

- Invite, deactivate and role-assign users; see last login and login method.
- Shorten chat-history retention from the 30-day maximum, to 1 day in Phase 1a (expiry is applied at read time, so 0 would hide a conversation before its first answer); a true "no history" setting of 0 comes with the Phase 1b purge job. The maximum cannot be raised.
- Set the default answer mode among those the operator enabled (cannot enable or disable modes).
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
- **Answer modes** per tenant: enable General knowledge and Web search; record the contractual basis (DPA clause reference) when enabling web search. This switch exists only in the operator console.
- **Login policy** per tenant: sign-in links on/off (default on), verified email domains, SSO source configuration (Entra tenant ID, Google hosted domain, OIDC/SAML metadata), MFA requirement for admins.
- Cross-tenant aggregates only: query volumes by mode, latency, cost per provider, error rates. No per-tenant query text.
- Vendor and model configuration: provider endpoints, model pins (Mistral Large by default), failover order, prompt template versions.
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
| Web-search boundary | The web-search tool is attached to the generation request only for tenants with the mode enabled; the tool query is the rewritten query only; the tool is pinned to Mistral's EU endpoint under the existing DPA and ZDR letter; every web-mode request audited |
| Own-analysis downloads | Served only to users whose package contains the document's tag; signed, short-lived download URLs; each download audited; per-user daily download cap to deter bulk export |
| Region and ZDR pin | Provider base URLs and model names in configuration with an allow-list; startup check refuses any host not on the allow-list, which separates EU hosts from the external hosts reachable only for tenants with the external-models entitlement (§14, Oct 19, 2026); ZDR letter references stored next to the configuration |
| Encryption | TLS 1.2+ at the proxy; Scaleway Private Network between hosts, WireGuard if a host ever sits outside it; encrypted volumes; backups encrypted with a key held in Scaleway Secret Manager |
| Metadata-only logs | Structured logging with an explicit allow-list of fields; request and response bodies never logged; linter rule and code-review checklist item |
| Rate limits and extraction detection | Redis token buckets per user and tenant (defaults sized well above 15 queries per user per day); anomaly rules (queries per minute, verbatim overlap of outputs with a single source, sequential pagination-like queries) raise alerts and apply temporary throttling |
| Prompt-injection resistance | Retrieval is read-only; no tools; crawled and web-fetched text is wrapped as untrusted context; output scanner for system-prompt leakage |
| Sign-in link hardening | Single-use tokens, 15-minute expiry, bound to the browser that requested them, per-address and per-IP rate limits, no account enumeration in responses |
| Audit log | Append-only table plus daily export to write-once object storage; events: auth (with method), admin actions, package changes, mode changes, source-register changes, takedowns, support access, every query (mode, metadata and cited chunk IDs or URLs, not text) |
| Secrets | Provider API keys, RAGFlow service key, the Transactional Email credential (and a Mailgun credential only while the backup is active), and database credentials in Scaleway Secret Manager; rotated on schedule and on staff departure |
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

- **Region**: Paris (fr-par) for Instances, Private Network, Object Storage, Secret Manager and Generative APIs. Email goes through Scaleway Transactional Email in fr-par, with Mailgun's EU region as an optional backup (revised Oct 20, 2026).
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
| Scaleway Transactional Email (fr-par) | a few thousand sign-in links per month | ~€0–5 (per-email pricing; Mailgun EU backup adds ~€0–35 only while active) |
| LLM usage, Mistral Large class (default) | 3,000 queries/day × ~7k tokens | ~€400–600 |
| Mistral web-search tool (tenants with the mode enabled) | per-call pricing on top of tokens | depends on share of web-mode queries |

Order of magnitude: €700–900 per month for infrastructure plus Mistral Large inference at 20 tenants, before web-search tool calls, monitoring extras and the annual pentest. Costs scale almost linearly with query volume on the LLM line only.

---

## 11. Phasing

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| 0 — Proof of value (4–6 weeks) | RAGFlow on one Scaleway Instance, a sample corpus, a thin login (sign-in link only) and chat UI, Mistral EU endpoint, corpus-only mode | Internal team and one friendly client get cited answers; eval set v1 exists |
| 1 — MVP (8–12 weeks) | Platform API with tenancy, packages, own generation path, corpus-only and general-knowledge modes, history with 30-day cap, excerpt-plus-link citations, content console, source register, audit log, retention jobs, Authentik with Entra, Google, OIDC/SAML and sign-in links, two-host deployment | Compliance guide's "before first client login" checklist complete; first paying tenants |
| 2 — Scale and assurance | Web-search mode (Mistral tool) with its DPA clause and UI labelling, tenant admin dashboard, extraction detection tuning, provider failover drills, trust page; SOC 2 observation window starts | SOC 2 Type I; three or more tenants |
| 3 — Depth | Shared conversations, briefs, alerts, tenant self-service SSO, tenant API | Driven by client demand |

Web-search mode is placed in Phase 2 because it needs a DPA clause and new UI labelling; since it uses Mistral's own tool under the existing contract, no new sub-processor is added, and it can be pulled into Phase 1 if a launch client requires it.

---

## 12. Decisions log (from scoping)

| Topic | Decision |
| --- | --- |
| Login methods | Microsoft Entra ID, Google Workspace, generic OIDC/SAML SSO, and emailed sign-in links; realised through a self-hosted identity broker |
| Packaging | Client-specific packages composed by the platform operator from content tags; no self-service purchase. *DRAFT, Oct 22, 2026:* only from tags owned by that tenant (§15.4) |
| Licensing | Third-party licences assumed to permit text-and-data mining and excerpt display; register still records basis per document |
| Source access | Excerpt plus link to the original; no in-app full-document viewer |
| Answer modes | Corpus-only by default; operator may enable General knowledge and Web search per tenant |
| History retention | 30 days maximum, fixed; tenant admin may shorten |
| ZDR | Written zero-retention confirmations from Mistral and Scaleway are in hand |
| Assurance | SOC 2 (Security and Confidentiality); ISO 27001 not pursued now |
| Isolation | Logical isolation on a shared platform; no dedicated instances |
| Hosting | Scaleway, Paris; low load (10 users × 15 queries/day per tenant) |
| Web search provider | Mistral's built-in web-search tool under the existing Mistral DPA |
| Mode control | Only the platform operator enables modes, per tenant; tenant admins choose the default among enabled modes |
| Own-analysis access | Original DOCX/PPTX downloadable from the platform by entitled users |
| Sign-in links | Enabled for every tenant by default; operator can switch off per tenant |
| Model | Mistral Large class by default, version pinned (target). Phase 0 runs on Scaleway Generative APIs with `deepseek-v4.1-flash` after the Mistral workspace proved to have no API quota and no Large tier; see findings M2. Return to Mistral Large when the contract and tier are in place |

---

## 13. Assumptions to verify in Phase 0

Scoping is complete. These are technical assumptions the Phase 0 build should confirm before Phase 1 is committed.

1. **Mistral web-search tool coverage.** Confirm the tool is available on the EU endpoint for the pinned Large model, that calls through it are covered by the zero-retention letter, and what its per-call pricing is.
2. **RAGFlow retrieval API behaviour.** Confirm document-level metadata filters work as expected across multiple datasets in one call and that the same file linked into several datasets does not double-count in results.
3. **Authentik email-link stage.** Confirm browser binding and single-use behaviour with the transactional email provider (Scaleway Transactional Email when written; Mailgun since Oct 19, 2026), and that per-tenant brands can hide the link option where it is switched off.
4. **Embedding model quality.** Confirm the self-hosted multilingual model meets the eval set's retrieval hit-rate target; otherwise switch to `mistral-embed` under the same DPA.
5. **Host sizing.** Measure RAGFlow parse throughput and memory on the 8 vCPU / 32 GB retrieval host with a realistic corpus sample; resize before Phase 1 if needed.

---

## 14. Addendum (Oct 18, 2026): workspaces, model choice, reasoning, file list

Owner decisions of Oct 18, 2026. They extend §4.2, §5.1, §5.2, §7 and §11 and are specified for build in `design/specs/phase-1a-build-spec.md`. The compliance guide's addendum of the same date records the privacy consequences.

### 14.1 Workspaces

A tenant has one or more **workspaces**. A workspace is the unit a user chooses when starting a conversation and it carries:

- a set of content tags (its corpus), resolved to RAGFlow dataset IDs server-side exactly as a package is today. Tags may be shared between workspaces (a "common" corpus) and unique to one workspace; a document that belongs in both is de-duplicated after retrieval;
- an "additional instructions" prompt block, written by the tenant admin (Phase 1a) or any tenant user (Phase 2), inserted into a delimited section of the fixed platform system prompt. The platform block (grounding, citation format, abstention, instruction secrecy) is not overridable;
- a default answer mode among those the operator enabled for the tenant;
- a default model among those the operator enabled for the tenant, and a default reasoning setting.

The package builder (§7.4) assigns tags per workspace instead of per tenant; "package" in this document now means the union of a tenant's workspace tag sets, and §8 "package enforcement" applies per workspace. The workspace is chosen when a conversation is created, is fixed for that conversation, and is shown as a label on the conversation. A tenant with one workspace sees no chooser.

### 14.2 Model choice and reasoning

The operator enables, per tenant, a set of models from the configured catalogue and may enable **external models**, which are served by a non-EU provider under the compliance addendum. The user picks the model when starting a conversation; the choice is fixed for that conversation. The user may switch reasoning on or off per conversation; the setting maps to each model's native switch (DeepSeek and Qwen thinking on/off, GPT and Claude reasoning effort). Reasoning text is discarded, never shown or stored; the answer carries a "reasoning on" badge. Model and reasoning flag are stored on every message, included in the cache key and in the audit event. External models carry a per-tenant monthly spend cap set by the operator: a soft warning to the operator at 80 percent, and at 100 percent new conversations fall back to the workspace default model with a notice to the user.

Catalogue (pinned in `config/models.toml`): Scaleway `deepseek-v4.1-flash` (default and eval model) and `qwen3.8-27b`; OpenRouter `openai/gpt-6.1-sol` and `anthropic/claude-opus-5.5` with zero-data-retention routing enforced in the client. The eval harness runs on the default model only.

### 14.3 Workspace file list and downloads

Each workspace has a read-only page listing the PDF, DOCX and PPTX files in its corpus with publisher, title, publication date, canonical link and ingestion date, and crawled sites rolled up to the site with a page count. No search or filters. A listed file can be downloaded only when its source-register row is flagged `downloadable` (set per source from the licence basis, by the manifest at ingestion or by the operator; in practice our own DOCX and PPTX analyses, and third-party files only where the licence permits redistribution; never by default), through signed short-lived URLs, audited and capped per user per day. Files that are not downloadable show their canonical link. This supersedes the "collections only" package page of §7.1 and the own-analysis-only download rule of §7.1 and §12.

### 14.4 Phasing change

Phase 1 is split. **Phase 1a** (the first test client) ships multi-tenancy with workspaces, model choice, reasoning, the file list with downloads, Authentik with sign-in links, and the general-knowledge mode, on the Phase 0 single Instance. **Phase 1b** carries the rest of the Phase 1 scope: content console, source register approval flow, two-host deployment, retention jobs, SSO connectors. Phase 2 adds user-edited workspace prompts and the items in `design/specs/backlog.md`.

### 14.5 Decisions log additions

| Topic | Decision |
| --- | --- |
| EU-only inference | Dropped for tenants with "external models" enabled by the operator; hosting and data stores stay in the EU |
| External model provider | OpenRouter with ZDR routing; DPA, transfer impact assessment and the tenant's signed acceptance are on file before the entitlement is enabled (revised Oct 19, 2026) |
| Downloads | Licence-gated per source (`downloadable` flag set explicitly per manifest row, never by default); own analyses in practice, third-party only where the licence permits (revised Oct 19, 2026) |
| Retention purge | Read-time 30-day expiry is tested in Phase 1a; the purge job stays in Phase 1b |
| Model and workspace scope | Chosen per conversation, fixed for the conversation |
| Reasoning | On/off per conversation, text hidden, badge shown; default per workspace |
| Workspace prompts | Tenant admin edits in Phase 1a; any tenant user in Phase 2 with versioning and admin revert |
| Tenant names in prompts | Permitted; matches flagged to the operator console and audit log, not to the user |
| Downloads (superseded Oct 19, 2026, see the row above) | PDF, DOCX and PPTX in the workspace corpus; single-use 60-second links, audited, capped; only sources flagged `downloadable` |
| Eval | Default model only (`deepseek-v4.1-flash`) |
| Email provider | Scaleway Transactional Email (fr-par) for every outbound email: sign-in links (Authentik's email stage over its SMTP relay) and the API's own mail (invitations, operator notices) over its HTTP API from `app.core.mail`. Mailgun EU region is an optional backup, switched on only by configuration after its DPA is filed; exactly one provider is active at a time (owner decision Oct 20, 2026, replacing the Oct 19 decision that made Mailgun the sole provider) |

---

## 15. Addendum (Oct 22, 2026): client-supplied documents

**DRAFT for owner and counsel review.** Owner decision 11 of Oct 22, 2026 (`design/specs/phase-1b-build-spec.md`, item P1b-19, step 1). This section is a **design to be built in a later item** (P1b-19 step 2, in Phase 1b if the second client arrives during the phase, otherwise Phase 2). Nothing in it is built; where it names a column, job or check, that is the specification for step 2, not a description of the code. The compliance guide's addendum of the same date records the privacy and contract consequences; where the two disagree, the compliance guide wins. Open points are collected in `design/compliance/open-questions.md`, section J.

### 15.1 Two content models

The design so far assumed one content model: public and open-source sources chosen and licensed by us, plus our own analysis (§1, §6). From this addendum two models coexist.

| | Model 1: platform-gathered | Model 2: client-supplied |
| --- | --- | --- |
| Who chooses the files | The platform (content editor and reviewer) | The client, which sends us the files for its workspaces and is the main driver of its corpus |
| What they are | Published third-party PDFs, crawled public pages, our own DOCX/PPTX analysis | Whatever the client sends within the accepted formats (§15.3): its own reports, licensed material it holds, internal documents |
| Who holds the right to use and redistribute | Us, recorded per source in the register (licence name, letter, "own work") | The client, by its written declaration and warranty (§15.5) |
| GDPR role for personal data in the files | Controller (compliance guide data map) | Processor for the client (§15.10) |
| Where they may be placed | Only tags owned by the tenant they are gathered for; the same source may be ingested into several tenants' own tags as separate copies (§15.4) | Only tags owned by the supplying tenant (§15.4) |
| Applies to | The current test client `cc` (unchanged: its three workspaces and `cc-shared` use only this model) and the internal tenant | Later clients that sign the client-supplied terms |

The models combine: a model-2 client's workspaces hold its own files and **may be supplemented** by platform-gathered content, ingested into the client's own tags. A model-2 source is never moved to model 1 or the reverse; a file that both we and a client hold is two separate sources (§15.4, de-duplication).

### 15.2 Source register: the `client-supplied` licence basis

The register (§6.1) stays one operator-owned table outside tenant RLS, as in Phase 0 and P1b-01. Added for model 2:

| Column | Rule |
| --- | --- |
| `licence_basis_kind` | Enumerated kind beside the existing free-text basis: `licensed`, `permission`, `own_work`, `open_licence`, `public_web`, `client_supplied` (names for step 2 to settle; today the basis is free text, P1b-05 and decision 10) |
| `supplying_tenant_id` | Set if and only if the kind is `client_supplied`; a check constraint enforces both directions. Never changed after the row is created |
| `client_declaration_ref` | Required for `client_supplied`: the reference and date of the client's written declaration covering this file (§15.5). The declaration itself is kept in the owner's document store, like a licence letter, not in RAGFlow |
| `downloadable` | Unchanged column; for a `client_supplied` row it is set from the client's declaration, never by default (§15.6) |

The `client-supplied` basis is offered in the console's propose form (P1b-05) and in the manifest (P0-11), and only together with a supplying tenant chosen from the tenant list. The register remains the index for erasure: every client-supplied file, its datasets and its document IDs are found through `supplying_tenant_id`.

Workflow: a content editor proposes the files the client sent, a content reviewer approves, the worker ingests (P1b-01, P1b-02), as for model 1. The reviewer's check for model 2 is narrower than a licence review: format and size within limits, the declaration on file and covering the file, the tags owned by the supplying tenant, the file's **relevance to the purpose of the workspace** it is meant for (a content check the platform already does for every client batch; owner, Oct 22, 2026), and the special-category rule (§15.5) applied to what the declaration states and what the reviewer sees (§15.5, §15.10). The reviewer does not assess the client's rights; the client warrants them. A reviewer may reject a file and tell the client why.

**Intake channel.** The client sends files to us by email, by a link to a file share the client controls (for example SharePoint), or by another channel agreed with the client (owner, Oct 22, 2026), and an internal content editor registers them; there is no tenant-side upload. A tenant admin upload page is a later feature (in `backlog.md` by owner decision of Oct 22, 2026), because it adds a public write path for files and a tenant-facing content role. Copies we hold outside the platform (the email or download received, and our local working copy) and in the platform are deleted within 30 days after the contract ends, earlier when the client withdraws the file or asks us to, or as the law requires. (owner, Oct 22, 2026; the copies outside the platform raise open-questions J18).

### 15.3 Accepted files

PDF, DOCX and PPTX, as for model 1, up to 500 MB per file and 100 files per batch (owner, Oct 22, 2026); Markdown and HTML only by arrangement. A file over 500 MB is accepted and stored, but not ingested until we have consulted the client; we may then, with its agreement, convert it (OCR, or conversion to Markdown) to reduce its size, and ingest the converted file. Large files count against the single Instance's 100 GB volume, shared with RAGFlow's index (open-questions J7). Files are parsed by RAGFlow on the internal network, which has no public listener and makes no external calls (§4.4), so a hostile file reaches only the parser. A malware scan before parsing is in the backlog (owner decision Oct 22, 2026); until then the internal-network parser, the format limits and the reviewer's check are the controls.

### 15.4 Isolation: tenant-owned tags

**What already exists and still holds** (built in Phase 0 to Phase 1b):

- One RAGFlow dataset per tag; the retrieval call carries only the dataset IDs of the conversation's workspace, resolved server-side from the workspace's tags; a request body with dataset or document IDs is refused (§4.4, §8, P1a-04).
- Workspaces, conversations, messages, citations and downloads sit in tenant tables with forced RLS and `tenant_id`-first indexes; the API sets the tenant from the token.
- Chunks from datasets outside the workspace are dropped before the prompt (`select_context`); the file list and downloads answer only for sources in the workspace's tags, and 404 otherwise (P1a-14).
- Answer cache keys are tenant-prefixed (`app.core.cache`).
- Changing a source's tags needs a reviewer (P1b-01, findings A1-6); the operator console offers only the page's tenant's tags plus shared tags (P1b-12; the "plus shared tags" part is removed in step 2, below).

These controls keep one tenant's **queries** and **workspaces** apart. They do not stop the operator from putting one tag into two tenants' workspaces: tags have no owner today. **Owner decision of Oct 22, 2026 (open-questions J9): a tag may be shared only between workspaces of the same tenant and must never be used to share documents across tenants, for any content, even if this means the same file sits several times in the shared RAG index under different tenants.**

**What is new for model 2:**

1. **Tag ownership.** Each tag gains an owner: `owner_tenant_id` on the tag record (the `datasets` table, or a `tags` table if step 2 moves tags out of `config/tags.toml`), never null: every tag belongs to exactly one tenant (the internal tenant for our own working and eval tags, such as `sample-*`). A **shared tag** is a tag shared by several workspaces **of its owning tenant** (a tenant's "common" corpus, as `cc-shared` is for `cc`); it sits in no other tenant's workspace (owner decision Oct 22, 2026, open-questions J9). Tag names carry the tenant's slug (`<tenant-slug>-<topic>`, as `cc` already does; client-supplied collections `client-<slug>`, §4.4). The `cc` tags already meet the rule: step 2 only records `cc` as their owner.
2. **Placement rule.** A `client_supplied` source may be linked only to tags whose `owner_tenant_id` equals its `supplying_tenant_id`. Enforced at proposal, at approval, at re-tagging and again by the worker before every upload to a dataset (the worker re-reads both values from the database; a mismatch fails the job with an error code and no upload). A database constraint or trigger on the source-to-tag mapping enforces the same rule, so a direct write cannot bypass the API.
3. **Workspace rule.** The operator's workspace routes refuse a tag owned by another tenant (`foreign_tag`), whatever the console offers; enforced in the API and by a database check on `workspaces.tag_ids` against tag ownership.
4. **De-duplication per owner.** Today a file whose content hash is already ingested is linked into the new tags of the existing source (findings E3). For model 2 de-duplication is scoped to the supplying tenant: a client-supplied file never merges with a platform source or with another tenant's source, even when the bytes are identical; it becomes its own source row and its own RAGFlow documents. The same applies in reverse (a platform file never joins a client's source). For platform-gathered content the existing re-tagging path (findings E3) already uploads a separate RAGFlow document into each new tag's dataset; with tenant-owned tags, giving one public report to two tenants therefore means two copies, one in each tenant's datasets, parsed twice and stored twice. The register keeps one row for our licence record, so a licence takedown still withdraws every copy (open-questions J19).
5. **Content store.** Copies of client-supplied files and declarations are stored under `[files] content_root` in a per-tenant directory (`clients/<tenant_id>/`), so that withdrawal and termination can be verified file by file and a directory listing proves nothing is left.
6. **Ownership is immutable** while the tag has documents: changing a tag's owner requires an empty dataset.

Platform-gathered content reaches a tenant only through that tenant's own tags; there are no cross-tenant platform tags. The cost is duplicate parsing and storage of content several tenants use (disk: open-questions J7).

RAGFlow remains one shared instance; tenant ownership lives in our database, not in RAGFlow (§1, "Tenant boundary"). A dedicated RAGFlow instance or index per client is not offered: a client's request for one is refused, unless a signed contract already obliges us to provide it (owner decision Oct 22, 2026, open-questions J15; compliance guide, decisions closed Oct 17).

### 15.5 The client's warranty and declaration

Before a model-2 client's first file is registered, the client signs the client-supplied terms (terms of service §6A, DPA clause 7A). For each file or batch it sends a declaration naming the files and stating, per file: that it has the right to supply it for this service, including parsing, indexing, sending excerpts to the language models named in the DPA, and showing excerpts to its own users; whether its users may download it (§15.6); whether it contains personal data of people other than the client's staff; and whether it contains special-category data, and if so which case of the rule below applies. The client indemnifies us against third-party claims arising from files it supplied. The reference of the declaration goes into `client_declaration_ref`.

**Special-category data (GDPR Art. 9, and criminal-offence data under Art. 10)** follows one three-way rule for every file, client-supplied or platform-gathered (owner decision Oct 22, 2026, open-questions J13; counsel to confirm):

| Case | Example | Handling |
| --- | --- | --- |
| (a) Made public by the person themselves | An autobiography describing the author's ethnic origin; the person's own interview or public statement | Accepted. Art. 9(2)(e) ("manifestly made public by the data subject") lifts the prohibition; an ordinary Art. 6 basis, transparency and the right to object still apply. Declared in the batch declaration for client files |
| (b) Revealed about a person by someone else | A biography or press article stating a named person's ethnicity, health or religion | Accepted only after the reviewer checks it and, for client files, the client confirms in writing its legal basis as controller; otherwise refused, or a redacted copy ingested |
| (c) Not public | HR files, medical records, union membership lists | Refused |

Aggregate or anonymous figures (for example a diversity percentage in an annual report) are not personal data and need no handling. Whatever is accepted is never used to search or profile people by these traits: there is no person search (§7), and the terms forbid profiling.

### 15.6 Downloads

A client-supplied file is downloadable only when the client's declaration says so; the `downloadable` flag is set from the declaration, never by default, and changed only on the client's written instruction. Downloads are served only to users of the supplying tenant, through the existing route: the file is listed only in workspaces whose tags contain it, and those tags are owned by the supplying tenant (§15.4). Single-use 60-second links, the per-user daily cap and the `download` audit event apply unchanged (P1a-14).

### 15.7 Withdrawal and takedown

- **On the client's request.** A tenant admin asks in writing ([privacy contact email] or support) to withdraw one or more of its files; the operator records the request and runs the existing `withdraw_source` job (P1b-03): documents deleted from every dataset, answer caches citing them purged, register row withdrawn with reason and date, stored citations flagged. Target: within 10 working days of the request (owner decision Oct 22, 2026). A tenant admin action in the app is a later feature (backlog).
- **On a third party's claim** (a publisher or a person named in a client file, or a data subject's request we receive directly): we may withdraw the file at once on receipt of the third party's notice, without waiting for the client's instruction (owner decision Oct 22, 2026; expected to be rare), and tell the client without undue delay; the client may contest the claim and, once it is resolved in the client's favour, instruct us to re-ingest the file. A data subject's request about a client file is forwarded to the client (§15.10), not acted on by us alone.
- **Stored excerpts.** When the client withdraws its own file, excerpts in its past conversations are kept, labelled "withdrawn" (owner decision Oct 22, 2026). Withdrawals on a third party's licence or rights claim follow decision 5 of Oct 22: excerpts blanked. For client-supplied files the stored citations sit only in the supplying tenant's own conversations.
- Copies in the content store (§15.4 item 5) and our copies outside the platform (§15.2) are deleted with the withdrawal.

### 15.8 Termination

The per-tenant termination purge (P1b-14) gains a client-content step, before the account data is deleted: withdraw every source with that `supplying_tenant_id` (RAGFlow file, parsed text, chunks and embeddings deleted from every dataset), delete the tenant-owned tags' datasets, delete the files and declarations under `clients/<tenant_id>/`, and reduce the register rows to an ID, the tenant ID, the withdrawal date and reason, with title, publisher, canonical link and hash erased. The certificate of deletion (`offboarding-pack.md`) gains the figures: client-supplied documents deleted, datasets deleted, files removed from the content store. Encrypted backups taken before the purge age out after the backup retention period, as for account data. Before termination the client may ask for its files back; we return the copies we hold as received (the export window of the terms, §13.3).

During the term, client-supplied files are kept until the client withdraws them; the 30-day maximum applies to chat history, not to the corpus.

### 15.9 What the language model sees

Unchanged in shape: the prompt carries the system prompt, the workspace's additional-instructions block, retrieved chunks with provenance (publisher, title, date, page), conversation turns and the question (CLAUDE.md). Chunks from client-supplied files are retrieved chunks like any other. Consequences:

- They go to the EU provider (Scaleway Generative APIs, Paris) under the Scaleway DPA and its zero-retention terms, and to OpenRouter **only** for a tenant with the external-models entitlement, under the same conditions as today (zero-data-retention routing, signed acceptance, spend cap; including the entitled-tenant failover of decision 2). A model-2 client that wants its files kept in the EU does not accept external models.
- The API adds no tenant, user or package identifier. A client's own files may contain the client's name or staff names, and the provenance fields (publisher, title) are taken from the declaration. This is tenant-supplied text under the same exception as the workspace instructions (compliance addendum Oct 18): permitted, not stripped. The tenant-name flag (P1a-07, findings B12) is run on the declared metadata at registration, raising a notice to the operator; it is not run on chunk text, where the client's own name is expected.
- **Prompt safety.** File text is data, never instructions. Today `html` and `markdown` passages are wrapped as untrusted (§8). For model 2 every client-supplied passage is wrapped as untrusted whatever its file type, and the guardrail eval gains a case with an instruction planted in a supplied PDF. The model has no tools (§8), so a planted instruction can at worst distort the answer in the supplying tenant's own workspace; it cannot reach another tenant.
- **Relevance review and eval.** Two different things. (a) *Relevance review* (built into intake, §15.2): a content reviewer checks that each file the client sends fits the purpose of the target workspace and may reject it with a reason; this is existing practice and needs no extra agreement beyond the terms (§6A.1). (b) *Automated evaluation* of answer quality (§9) on a client's corpus, if ever done: synthetic questions written against the client's files, run in the client's own workspace, with only scores (hit rate, faithfulness and similar) committed to the repository, never the questions, answers or file text (CLAUDE.md), Allowed by default under the terms (§6A.5), because the questions are written from the client's confidential files and the client agrees to it by contract; not done where the client's contract excludes it (order form A.8; owner decision Oct 22, 2026, open-questions J16).

### 15.10 GDPR roles

Client-supplied files are Client Data. Personal data in them is processed by us as **processor** on the client's instructions under the DPA (clause 7A); the client is the controller and carries the controller's duties for it, including Article 14 transparency to people named in its files and the legal basis for supplying them. Platform-gathered content in the same workspace stays under our controller role (compliance guide data map; `legitimate-interest-assessment.md`). One prompt can therefore carry processor data (the question, the turns, client-file chunks) and controller data (public-source chunks), as the transfer impact assessment already describes for the external-models hop.

### 15.11 What changes elsewhere

| Document | Change |
| --- | --- |
| §1, §4.4, §6.1, §6.2, §14.3 | Read with this section; a short pointer is added to §4.4 and §6.1. The `cc` setup is unchanged |
| Compliance guide | Addendum of Oct 22, 2026 |
| `design/compliance/` | DPA clause 7A and Annexes; terms §1.2, §3.1, §6A and Annex A.8; privacy notice §1, §4 and Part B §13; transfer impact assessment §3 and §7; sub-processors (no new sub-processor; data received widened); records of processing; DPIA; LIA scope; AI Act documentation §5.4; security questionnaire; onboarding and offboarding packs; trust page; risk register; open questions J |
| Stack Decision | No change: no new technology |
| Code, config, migrations | None in step 1 |

### 15.12 Build in step 2 (for the later spec item)

Register columns and constraints (§15.2); tag ownership and the placement, workspace and de-duplication rules (§15.4); per-tenant content-store directory; console and manifest support for the basis and the supplying tenant; tenant-name flag on declared metadata; untrusted wrapping for every client-supplied passage; termination purge step and certificate figures. Owner for every existing tag (internal tenant for `sample-*`, `cc` for `cc-*`); the operator console and API offer and accept only the page tenant's own tags (removes P1b-12's "plus shared tags"). Tests, each proving the negative case: a tag cannot be placed in a workspace of a tenant other than its owner; a tag cannot be created without an owner; a client-supplied source cannot be linked to another tenant's tag (API, worker and database); a workspace of tenant B cannot take a tag owned by tenant A; a query in tenant B's workspace never retrieves, lists or downloads tenant A's client-supplied file; an identical file supplied by two tenants yields two sources; the termination purge leaves no document, dataset, content-store file or register title for the tenant; the prompt for a client-supplied chunk contains no identifier added by the API; the worker refuses a job whose tags no longer match the supplying tenant.

### 15.13 Decisions log additions

| Topic | Decision |
| --- | --- |
| Content models | Two models: platform-gathered (as today, `cc`) and client-supplied (later clients, client-driven, platform may supplement); owner decision 11, Oct 22, 2026 |
| Tag ownership | Every tag belongs to one tenant; shared tags are shared only between workspaces of that tenant and never across tenants, for all content, accepting duplicate copies in the index (owner, Oct 22, 2026; DRAFT) |
| Client-supplied isolation | Register basis `client-supplied` with the supplying tenant; such sources only in tags owned by that tenant, never in another tenant's workspace; de-duplication per owner (DRAFT) |
| Rights in client files | Client's warranty and indemnity; declaration per file or batch; the client decides downloadability (DRAFT, counsel to review) |
| GDPR role for client files | Processor for the client (DRAFT, counsel to confirm) |
