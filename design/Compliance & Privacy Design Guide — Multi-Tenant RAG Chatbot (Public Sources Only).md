# Compliance & Privacy Design Guide — Multi-Tenant RAG Chatbot (Public Sources Only)

Oct 17, 2026 · @Daniel Riveong

## Scope and what changes

With a corpus built only from public third-party sources and your own analysis, the protected asset shifts from client documents to client queries and chat history, and the main legal exposure shifts from GDPR processing to content licensing. Compliance gets lighter, not optional.

Assumptions:

- The RAG corpus holds only published third-party PDFs, crawled public websites and your own DOCX/PPTX analysis. Clients upload nothing.
- Application, vector index, object storage, logs and backups are hosted in the EU.
- The LLM is called through an API provider under a signed DPA with contractual Zero Data Retention and EU in-region processing.
- Clients are businesses; their employees log in and query. Tenants may see different slices of the corpus (entitlements) but share the same underlying index.

What simplifies compared with the default design:

- No per-tenant document isolation for the corpus; a shared index with entitlement filters is sufficient.
- No client-content erasure cascade, no deletion certificates for documents, no data-return obligations.
- A shorter DPA covering only account data, queries and chat history.
- The DPIA is lighter; the TIA still applies to the LLM hop.

What does not simplify:

- Queries reveal what a client is researching, often commercially sensitive. Query confidentiality between tenants is the core privacy promise.
- Public sources still contain personal data (authors, named executives, people quoted). You are the controller for that data and owe transparency and erasure duties.
- Licensing, scraping terms and takedowns become the primary legal risk and need a source register and a process.
- SOC 2 scope is nearly unchanged; auditors care about confidentiality of query data and integrity of the service, not only about uploaded files.

## Data map and roles

You are the controller for the corpus and for account data, and a processor only for client queries and chat history; most of your GDPR work now sits on the controller side.

| Data category | Examples | Your GDPR role | Personal data likely? | Default retention |
| --- | --- | --- | --- | --- |
| Public third-party content | Published reports, crawled pages, filings | Controller | Sometimes (authors, named individuals) | While licensed and relevant; removed on takedown |
| Your own analysis | Internal DOCX/PPTX | Controller | Rarely | Business need |
| Derived corpus data | Chunks, embeddings, parsed text | Controller | Inherits from source | Same as source |
| Client queries and chat history | Query text, answers, cited chunks | Processor | Yes (queries may name people; reveal client intent) | Tenant-configurable, default 30 days |
| Account data | Logins, roles, SSO identifiers | Controller | Yes | Life of account + legal hold |
| Usage analytics | Query volumes, topics by tenant | Controller | Pseudonymous | 24 months, aggregated |
| Audit and security logs | Auth events, admin actions, query metadata | Controller | Yes (user IDs) | 12 months, immutable |
| LLM request/response | Prompt with chunks, model output | Processor; LLM vendor is sub-processor | Yes | Zero at vendor (ZDR); metadata only on your side |

Two points to settle early: whether you will use query data across tenants to improve retrieval (if so, only in aggregated, pseudonymised form and disclosed in the contract), and the shorter default chat-history retention, since clients lose little by having their research trail expire quickly.

A data-flow drawing follows at the end of the architecture section.

## Architecture and software controls

Share the corpus, isolate the conversations: one index with entitlement filters, and strict per-tenant separation of queries, history and analytics.

**Corpus and entitlements**

- One shared vector index and document store. Each document carries an entitlement tag (public tier, premium tier, client-specific package); the API injects the tenant's entitlement set into every retrieval, never the client.
- A source register table: URL or file, publisher, licence or permission basis, fetch date, entitlement tag, review date, takedown status. This is your evidence for licensing questions and your index for takedowns.
- An automated entitlement test in CI: a tenant with tier A must never retrieve tier B chunks.

**Query and history isolation**

- Chat history stored with tenant ID and row-level security; no cross-tenant joins in application code.
- Semantic or answer caches keyed by tenant; never serve a cached answer generated for another tenant.
- Usage analytics aggregated per tenant; cross-tenant trend analysis only on pseudonymised, aggregated data with a minimum group size.

**Encryption and keys**

- TLS 1.2+ everywhere. At-rest encryption for history and account data with a per-tenant KMS key where feasible; the shared corpus uses a platform key.

**Data minimisation at the model boundary**

- Send the model the query, retrieved chunks and the system prompt only. No tenant name, user ID or entitlement information.
- Cap chunk count and length.

**Retention by design**

- Chat history TTL per tenant, default 30 days, configurable to 0.
- Application and gateway logs hold metadata only (request ID, token counts, latency, status). Debug logging of bodies is a code-review blocker.
- Backups encrypted, EU-region, defined retention, per-tenant purge of history and account data tested.

**Corpus erasure and takedown**

- A single delete job per source ID that removes the original file, parsed text, chunks, embeddings and cache entries, and marks the source register entry. Citations in stored chat history are retained but flagged as withdrawn.
- Takedown requests (publisher or data subject) processed within a defined window, for example 10 working days.

**Prompt-injection and content safety**

- Crawled pages are untrusted input. Retrieval is read-only; no tools that can send, fetch or write.
- Output scanning for leaked system prompts and for strings matching other tenants' identifiers.
- Rate limits per user and tenant; detection of bulk extraction attempts, which also protects licensed content from being siphoned out.

**Audit logging**

- Log who queried, when, which chunks were retrieved and cited, and all admin and source-register actions. Write-once storage in the EU, 12-month retention.

**Authentication and access**

- SSO (OIDC or SAML) per tenant, MFA for your staff and tenant admins, RBAC (tenant admin, analyst, auditor). Support access time-boxed and logged.

**Answer quality and traceability**

- Every answer cites its source chunks and shows source provenance (publisher, date). Store the citation set with each chat record.
- A versioned evaluation set run on every retrieval or prompt change; build it from your own licensed corpus, which you now control.

&#91;embedded content: data flow · shared corpus, isolated queries, EU boundary\]

The corpus is one shared index filtered by entitlement; what must never cross tenants is the query stream and chat history, and the only outbound call carries the query and retrieved chunks to a ZDR endpoint.

## SOC 2 programme

Scope Security and Confidentiality; add Privacy only if clients ask for it, since the personal data you process for them is limited to logins and queries. Plan 6 to 9 months to a Type II report.

| Workstream | What the auditor expects | Owner |
| --- | --- | --- |
| Policies | Information security, access control, change management, incident response, vendor management, data retention, acceptable use, content sourcing | Security lead |
| Risk assessment | Annual register; AI and content risks listed: cross-tenant query leakage, prompt injection via crawled pages, licence breach, vendor retention change | Security lead |
| Access control | SSO and MFA for staff, quarterly access reviews, offboarding within 24 hours | IT / Eng |
| Change management | PR review, CI gates including the entitlement test, deployment separation | Engineering |
| Vendor management | Sub-processor inventory with SOC 2 or ISO 27001 reports; LLM provider DPA and ZDR letter; content licence inventory | Security lead |
| Monitoring | Centralised logs, alerts on auth anomalies and bulk-extraction patterns, weekly vulnerability scans, annual pentest | Engineering |
| Incident response | Runbook, client notification timing, annual tabletop | Security lead |
| People | Background checks where lawful, annual security training, confidentiality terms | HR |

Practical points:

- Query confidentiality is the control auditors and client reviewers will probe: show the tenant-scoped history store, the cache keying and the aggregated-analytics rule.
- Keep the content-sourcing policy and source register in scope as a Confidentiality and integrity control; it demonstrates you know what is in the index and on what terms.
- A compliance automation platform still pays for itself from the first audit.

## GDPR and legal contracts

The client DPA shrinks to queries, history and account data; the heavier legal work moves to content licensing, crawling terms and your controller duties over personal data found in public sources.

**Client DPA (Article 28), reduced scope**

- Processing covered: user accounts, queries, chat history, usage data. State explicitly that clients upload no content.
- Instructions, confidentiality, TOMs annex, sub-processor list with notice period, breach notification window, deletion of history and accounts at termination.
- A query-confidentiality clause: queries and history are never shared with or visible to other tenants, and are used for service improvement only in aggregated, pseudonymised form if at all.
- Audit rights satisfied by the SOC 2 report.

**Sub-processor chain**

- LLM provider: DPA, SCCs where processing or support is outside the EU, ZDR arrangement, EU region pin.
- Cloud, email, monitoring and error-tracking vendors: DPAs on file; confirm none receive query bodies by default.

**Controller duties over public-source personal data**

- Legal basis is usually legitimate interests (Article 6(1)(f)); record a legitimate interests assessment covering why indexing published material for research is proportionate.
- Transparency (Article 14): where data subjects were not told directly, a public privacy notice describing the sources and purposes is the standard route; a disproportionate-effort argument should be documented.
- Erasure and objection requests: remove or redact the person's data from the corpus (document-level removal or re-ingestion of a redacted copy) within 30 days, and record the decision.
- Avoid ingesting special-category data from public sources unless there is a clear basis; filter obvious cases at crawl time.

**Content licensing and crawling (primary legal risk)**

- Review publisher licences before ingesting PDFs; many research licences bar redistribution, text-and-data mining or AI use. Where in doubt, obtain written permission or exclude the document.
- Honour robots.txt, site terms and the EU text-and-data-mining opt-out (DSM Directive Article 4): if a site has reserved rights in a machine-readable way, do not crawl it.
- Keep the source register current with licence basis and review date; it is your defence in a dispute.
- Serve citations and short excerpts, not full reproductions, and block bulk extraction.
- Takedown process with a named contact and a response window.

**Accountability documents**

- Records of processing (Article 30) for both roles.
- A DPIA is still advisable (large-scale indexing of public personal data plus AI processing), but it is shorter and focuses on data-subject rights and accuracy.
- A Transfer Impact Assessment for the LLM hop if the provider is subject to non-EU law.

**EU AI Act**

- AI transparency notice to users; label generated content; keep technical documentation of model, provider, sources and evaluation.
- Reassess if a client uses outputs for decisions in a high-risk category.

**Terms of service**

- Query confidentiality and no-training commitments.
- Output disclaimer: research assistance with citations; third-party content accuracy not warranted.
- Prohibition on bulk extraction or redistribution of corpus content; suspension rights.
- Liability cap.

## Zero data retention and privacy best practices

With no client documents in the index, ZDR protects one thing above all: what each client is asking. Treat the query stream as the confidential asset and verify ZDR terms per model and endpoint, in writing.

- Obtain the provider's written ZDR confirmation naming your organisation ID, covered models and endpoints; keep it with the DPA.
- Check for model-specific retention requirements that override ZDR; pin model versions and re-check terms before upgrading.
- Use EU inference endpoints and hard-code the region; a global endpoint does not prove in-region processing.
- Avoid provider-side file storage, batch, assistants or fine-tuning endpoints; they commonly fall outside ZDR.
- Confirm how provider prompt caching is treated under your contract; disable it for tenants that require strict ZDR.
- Disclose the standard abuse-monitoring exception (retention where required by law or to investigate misuse) in the DPA.
- Keep your own query logs to metadata; where product analytics need query text, store it pseudonymised, per tenant, with a short TTL.
- Never debug with real client queries; keep a synthetic query set for evaluation.
- Run an annual ZDR verification and record it as audit evidence.
- Publish a trust page: sub-processors, data-flow diagram, retention table, source-register summary, certifications, takedown and data subject request contacts.

## Control-to-framework mapping

The register is shorter than the default design's, and two controls that did not exist there (entitlement enforcement, content licensing) now carry real weight.

| Control | SOC 2 criterion (TSC 2017) | GDPR basis | Evidence |
| --- | --- | --- | --- |
| Entitlement enforcement on the shared corpus, CI test | CC6.1, CC6.3, C1.1 | Art. 32 | CI test results, entitlement design doc |
| Query and chat-history isolation (RLS, tenant-keyed cache) | CC6.1, C1.1 | Art. 5(1)(f), Art. 25, Art. 32 | RLS policies, cache key review |
| Aggregated, pseudonymised analytics only | C1.1, P4.1 | Art. 5(1)(c), Art. 25, Recital 26 | Analytics pipeline doc |
| Encryption in transit and at rest | CC6.1, CC6.7 | Art. 32(1)(a) | KMS config, TLS scan |
| Data minimisation at the model boundary | CC6.7 | Art. 5(1)(c), Art. 25 | Prompt template review |
| Retention schedule and TTLs for history and logs | CC6.5 | Art. 5(1)(e), Art. 17 | Retention policy, TTL config |
| Corpus takedown and erasure job | CC6.5, CC2.3 | Art. 17, Art. 21 | Source register, delete job runs |
| Source register and content licensing review | CC2.3, CC9.2, C1.1 | Art. 6(1)(f), Art. 14; DSM Art. 4 | Register, licence files, LIA |
| Bulk-extraction detection and rate limits | CC6.6, CC7.2 | Art. 32 | Alert config, incident samples |
| Audit logging, immutable, 12 months | CC7.2, CC7.3 | Art. 30, Art. 32 | Log config, exports |
| SSO, MFA, RBAC, quarterly access review | CC6.1, CC6.2, CC6.3 | Art. 32 | IdP config, sign-offs |
| Change management with PR review and CI gates | CC8.1 | Art. 25, Art. 32 | Branch protection, PR history |
| Vulnerability scanning and annual pentest | CC7.1 | Art. 32(1)(d) | Reports |
| Incident response and breach notification | CC7.4, CC7.5 | Art. 33, Art. 34 | Runbook, tabletop minutes |
| Vendor and sub-processor management | CC9.2 | Art. 28(2), Art. 28(4) | Sub-processor list, DPAs |
| LLM ZDR and EU region pin | CC6.7, CC9.2, C1.2 | Art. 28, Art. 44 to 46 | ZDR letter, endpoint config |
| Client DPA (reduced scope) and TOMs | CC2.3 | Art. 28(3) | Signed DPAs |
| Records of processing, DPIA, TIA, LIA | P1.1 (if Privacy in scope) | Art. 30, Art. 35, Art. 46, Art. 6(1)(f) | The documents |
| Data subject and takedown request handling | P5.1, P6.1 (if in scope) | Art. 12 to 22 | Request log |
| AI transparency notice and technical documentation | CC2.2 | EU AI Act Art. 50; GDPR Art. 14 | UI notice, model docs |

Criterion references are indicative; confirm with your auditor.

## Implementation checklist and open decisions

Before first client login:

- [ ] LLM provider DPA signed; ZDR confirmation on file naming models and endpoints
- [ ] EU region pinned in code for inference, storage, index, logs and backups
- [ ] Source register populated with licence basis for every ingested document and crawl
- [ ] Entitlement test and query-isolation test running in CI
- [ ] Chat history TTL and metadata-only logging verified
- [ ] SSO, MFA and RBAC live; admin and source-register actions audited
- [ ] Public privacy notice covering public-source personal data; takedown contact published
- [ ] Reduced-scope client DPA and ToS approved by counsel
- [ ] AI transparency notice in the UI

Before SOC 2 observation window:

- [ ] Policies approved, including content sourcing; compliance automation platform connected
- [ ] Sub-processor and content-licence inventories complete
- [ ] Vulnerability scanning and pentest scheduled; bulk-extraction alerts tuned
- [ ] Incident tabletop completed
- [ ] Trust page published

Open decisions:

- Default chat-history retention (0, 7 or 30 days) and whether tenants may extend it.
- Whether to use cross-tenant query data for retrieval tuning at all; if yes, the aggregation threshold.
- Entitlement model: flat tiers versus per-client packages, and whether a client-specific package ever justifies a separate index.
- Whether to pursue ISO 27001 alongside SOC 2 for EU procurement.

## Addendum (Oct 17, 2026): answer modes, sign-in links and fixed retention

Scoping decisions recorded in the Platform Architecture & Functional Design document change three points above.

**Answer modes.** Corpus-only remains the default. Two optional modes exist, enabled per tenant by the platform operator:

- *General knowledge*: the model may add its own knowledge where the corpus is silent. No new data flow; the only change is that uncited sentences are visibly marked and the answer carries a banner. Keep the output disclaimer in the terms of service broad enough to cover uncited content.
- *Web search*: the rewritten query is sent to a web search provider and the top result pages are fetched server-side. This adds a sub-processor that receives query text. Requirements: the provider is listed in the sub-processor list with a DPA and, where applicable, SCCs and a TIA; the mode is covered by an explicit clause in the client DPA and is enabled only for tenants that have accepted it; only the rewritten query is sent, never chat history or corpus chunks; fetched web text is treated as untrusted input and is never written to the corpus; web citations are labelled separately from corpus citations; every search call is audited with tenant, mode and timestamp. Add "web-search provider retention change" and "licensed content displaced by web content" to the risk register.

**Sign-in links by email.** Emailed single-use links are an accepted login method alongside SSO. The transactional email provider (Scaleway Transactional Email, Paris) becomes a sub-processor receiving user email addresses only. Controls: single-use tokens, 15-minute expiry, browser binding, rate limits, no account enumeration, second factor required for tenant admins. Map to CC6.1 and CC6.2. Added Oct 18, 2026: the link opens a landing page that requires a user action (a button whose POST submits the token) before the token is consumed, because corporate mail security scanners pre-fetch links and would otherwise spend the single-use token; a GET of the link never completes a login (CC6.1, availability of the login path).

**Retention.** Chat-history retention is fixed at a 30-day maximum; tenants may shorten it but not extend it. The "open decision" on retention above is closed. The DPA states the 30-day cap.

**Decisions closed.** Cross-tenant query data is not used for retrieval tuning beyond aggregated, pseudonymised metrics with a minimum group size. Packages are client-specific sets of content tags on a shared index; no separate index per client. ISO 27001 is not pursued now; SOC 2 Security and Confidentiality remains the target.

**Update (same day).** Web-search mode will use Mistral's built-in web-search tool on the EU endpoint, so no new sub-processor is added; confirm in writing that tool calls fall under the existing Mistral DPA and zero-retention letter, and disclose the mode in the client DPA as described above. Answer modes are enabled only by the platform operator per tenant. Our own DOCX/PPTX analysis is downloadable from the platform by entitled users; downloads are served through signed, short-lived URLs, audited and capped per user, and this is added to the bulk-extraction controls (CC6.6, CC7.2). Emailed sign-in links are on by default for every tenant and can be disabled per tenant by the operator.

**Update (Oct 18, 2026): Phase 0 inference provider.** During Phase 0 the active LLM provider is Scaleway Generative APIs (Paris region) with the model `deepseek-v4.1-flash`, because the Mistral workspace available to the team had no API quota and no Large tier. Scaleway was already listed as the second EU provider and sub-processor, so the data flow is unchanged: the only outbound call carrying query text goes to an EU endpoint under a DPA, and Scaleway states no retention for Generative APIs. Two points to confirm in writing before any client use: that the Scaleway no-retention statement covers this model and endpoint, and that the DPA names the Paris region. The model weights come from a non-EU developer, but inference, logs and retention are governed by Scaleway as the processor, which is what the GDPR analysis turns on. Mistral remains the target provider for Phase 1 once the contract and tier are in place.

## Addendum (Oct 18, 2026): non-EU model providers, tenant-authored prompts, file list and downloads

Owner decisions of Oct 18, 2026, recorded for the Phase 1 build. They change the EU-only assumption above and add three data flows.

**The EU-only requirement for the LLM hop is dropped.** Assumption 3 in "Scope and what changes" and the "EU region pinned in code for inference" checklist item are narrowed: hosting, index, storage, logs and backups stay in the EU (Scaleway, Paris); inference may leave the EU for tenants where the operator has enabled *external models*. Rationale: the first test client requires Claude and GPT-class models on day one, and no EU-pinned route for them exists under our contracts. The legal transfer obligation (GDPR Chapter V) does not disappear with the design rule; it is met as follows, deliberately kept light for the test client and to be revisited before the SOC 2 observation window:

- Provider: OpenRouter, reached over its OpenAI-compatible API with the zero-data-retention routing option set on every request and asserted by a test in our client code. OpenRouter's standard DPA with standard contractual clauses is accepted as published; no bespoke letter is sought.
- A one-page Transfer Impact Assessment written by us, kept with the sub-processor list, naming OpenRouter and the upstream model vendors it may route to.
- The feature is disclosed in the client DPA as an optional mode, like web search, and is enabled only for tenants that have accepted it. Default off.
- Tenants that have not accepted it are served by Scaleway only; the allow-list in `config/models.toml` is split into EU hosts and external hosts, and the API refuses an external model for a tenant without the entitlement.
- Risk register: "external provider retention change", "upstream vendor outside the published ZDR routing", "model cost overrun" (mitigated by a per-tenant spend cap with a hard stop and fallback to the workspace default model).

**Model choice and reasoning.** Users may pick a model per conversation from the set the operator enabled for the tenant (Scaleway `deepseek-v4.1-flash`, `qwen3.8-27b`; external `openai/gpt-6.1-sol`, `anthropic/claude-opus-5.5`) and switch reasoning on or off per conversation. The prompt content does not change by model; the data-minimisation control at the model boundary applies unchanged. Reasoning text is not shown to users and is not stored; the answer carries a "reasoning on" badge. The model and reasoning flag are stored on every message and in the audit event.

**Tenant-authored prompt instructions.** Each tenant workspace carries an "additional instructions" block written by the tenant admin (Phase 1) and later by any user of the tenant (Phase 2, versioned and revertible). It is appended inside a delimited section of the fixed platform system prompt and cannot relax the grounding, citation or abstention rules; an adversarial eval set proves this. Because the tenant writes it, it may contain the tenant's own name or staff names, which the "no tenant identifiers in prompts" control otherwise forbids. Decision: permitted as a tenant-authored exception. The API matches each saved prompt against the tenant display name, verified email domains and user names and, on a match, raises a notice in the operator console and an audit event; nothing is shown to the tenant user. Record the exception against CC6.7 and Art. 5(1)(c).

**File list and downloads.** Tenant users can see, per workspace, the list of PDF, DOCX and PPTX files in the workspace's corpus (publisher, title, publication date, canonical link, ingestion date), with crawled sites rolled up to the site and a page count. Users may download the files themselves, including third-party PDFs; the owner confirms the content licences for the test corpus permit this. Downloads go through signed, short-lived URLs, are audited and are capped per user per day, extending the bulk-extraction controls of the Oct 17 update (CC6.6, CC7.2). Licence basis stays internal and is not shown.
