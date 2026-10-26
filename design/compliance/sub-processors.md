# Sub-processor List

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 19, 2026 |
| Author | Drafted for owner review (spec item P1a-15) |
| Revision | Oct 22, 2026, **DRAFT**: client-supplied documents (P1b-19 step 1, architecture §15) add no sub-processor; the data received by Scaleway and, if enabled, the external-models chain widens |
| To finalise, the owner must | (1) record the SCC module and version of the OpenRouter DPA (signed Oct 23, 2026) and the acceptance date of the Scaleway DPA (version of June 1, 2024) in `paperwork-checklist.md`; (2) keep a dated copy of Scaleway's published zero-retention policy (Scaleway issues no letter; findings M2); (3) verify the AWS and Azure region constraint with one real request each (findings C32); (4) set the "date added" to the date each service first receives client personal data; (5) publish the customer-facing version with the trust page. |

Method: built from `config/models.toml` (allow-list, provider sections, catalogue), `infra/` (Compose files, Authentik SMTP settings, Caddy) and the Stack Decision. Every outbound host the API and workers reach is in `[allow_list]`; the API refuses to start otherwise.

## Active sub-processors

| Sub-processor | Service | Purpose | Data received | Location | Safeguard | When used | Date added |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Scaleway SAS (France) | Instances, Block Storage, Private Network; Object Storage for backups (Phase 1b) | Hosting the API, web app, database, Redis, RAGFlow index, the download content store, logs and backups | All platform data, encrypted at rest; for clients that supply documents (DRAFT, Oct 22, 2026), their documents, parsed text and index | Paris, France (fr-par) | EU processing; Scaleway DPA, version of June 1, 2024 (entered into; acceptance date to record) | Always | [date] |
| Scaleway SAS | Generative APIs (`api.scaleway.ai`), models `deepseek-v4.1-flash`, `qwen3.8-27b` | Default language-model inference, query rewrite | Prompt contents (system prompt, workspace instructions, public-source chunks and, for clients that supply documents, excerpts of their documents, conversation turns, question); no identifiers | European Union (Scaleway confirms the EU, not a named site) | EU processing; Scaleway DPA; Scaleway's published zero-retention policy for Generative APIs ("Understand the Generative APIs Privacy Policy", version of Oct 3, 2025, https://www.scaleway.com/en/docs/generative-apis/reference-content/data-privacy/); Scaleway issues no written confirmation, so the published policy is the evidence (owner, Oct 26, 2026; findings M2); provider prompt-caching treatment to confirm | Every tenant | [date] |
| Scaleway SAS | Transactional Email, region fr-par: SMTP relay `smtp.tem.scw.cloud` for Authentik's sign-in links; HTTP API for the platform's own mail (invitations, operator notices; Phase 1b) | Sending single-use sign-in links and platform mail | Recipient email address, the link, and the service's delivery logs (email content is deleted as soon as processing ends: when the recipient server accepts it, at the first hard bounce, or after 36 hours of failed attempts; spam-classified email after 72 hours, email held by a blocked domain after 15 days, encrypted backups kept 7 days; sending metadata, logs and activity history are kept while the sending domain is active, and Scaleway plans to shorten this in 2027; webhook data 15 days; no link rewriting) | Paris, France (fr-par) | EU processing; covered by the Scaleway DPA above (owner decision Oct 20, 2026) | Always | [date] |
| Mailgun Technologies, Inc. (Sinch), EU region — **optional backup, not active** | Transactional email: SMTP relay `smtp.eu.mailgun.org`, HTTP API `api.eu.mailgun.net`; activated only by configuration if Scaleway Transactional Email is unavailable | Sending single-use sign-in links and platform mail while active | Recipient email address, the link, and Mailgun's delivery logs (retention set to the shortest available; click and open tracking switched off) | EU region (Mailgun EU data centres) | Mailgun DPA with SCCs for any US-parent access **[reference, date accepted]**, filed before activation; EU region pinned in configuration (owner decisions Oct 19 and Oct 20, 2026) | None while inactive | [date] |

## Sub-processors for the optional external-models mode

Used only for a tenant whose signed acceptance is on file and for which the operator has enabled external models. Default off.

| Sub-processor | Service | Purpose | Data received | Location | Safeguard | Date added |
| --- | --- | --- | --- | --- | --- | --- |
| OpenRouter, Inc. (United States) | OpenAI-compatible API, EU endpoint `eu.openrouter.ai` | Routing prompts to the pinned upstream vendor | Prompt contents as above; our API key; no identifiers, no `user` field | Company: United States. API endpoint: EU (hosting location to verify) | OpenRouter DPA with SCCs, signed Oct 23, 2026 (SCC module [2/3] and version to record); TIA (`transfer-impact-assessment.md`); ZDR routing and `data_collection: deny` on every request | [date] |
| Amazon Web Services (Bedrock), upstream of OpenRouter | Inference for `anthropic/claude-opus-5.5` (pinned, no fallback) | Model inference | Prompt contents | EU, EEA, UK or Switzerland, as constrained by the region setting of each API request (owner, Oct 26, 2026; one real request to verify) | OpenRouter flow-down terms; on OpenRouter's ZDR list (to verify); SCCs and TIA | [date] |
| Microsoft (Azure), upstream of OpenRouter | Inference for `openai/gpt-6.1-sol` (pinned, no fallback) | Model inference | Prompt contents | EU, EEA, UK or Switzerland, as constrained by the region setting of each API request (owner, Oct 26, 2026; one real request to verify) | OpenRouter flow-down terms; on OpenRouter's ZDR list and free of prompt-retaining abuse monitoring (to verify); SCCs and TIA | [date] |

## Configured but not active

| Service | Status |
| --- | --- |
| Mistral AI (`api.mistral.ai`, Paris) | In the allow-list and `[mistral]` config, inactive since Phase 0 (`[llm] provider = "scaleway"`, findings M2). Not a sub-processor until activated; add here with notice to clients before first use. Web-search mode (Phase 2) depends on it. |

## Reviewed and not sub-processors

| Service | Why not |
| --- | --- |
| RAGFlow (Elasticsearch, MySQL, MinIO-compatible store, Valkey, TEI embedding model `bge-m3`) | Self-hosted on our Scaleway Instance on the private Compose network; no public listener, no external calls (it is configured with no LLM of its own, findings R11) |
| Authentik | Self-hosted on our Instance; sends mail through Scaleway Transactional Email's SMTP relay (listed above; Mailgun EU only while the backup is active) |
| PostgreSQL, Redis, Caddy | Self-hosted on our Instance |
| Prometheus, Grafana, Loki (Phase 1b) | Self-hosted; "no SaaS APM that receives bodies" (architecture §9) |
| Container registries (Docker Hub, GitHub Container Registry) | Images are pulled; no platform data is sent |
| Certificate authority used by Caddy for TLS | Receives only our public hostname |
| GitHub (source code, CI) | Holds code and synthetic fixtures only; no client data, real queries or secrets (CLAUDE.md) |
| Public websites fetched by the crawler | We fetch from them; they receive no client data |

## Client-supplied documents

*DRAFT, Oct 22, 2026 (P1b-19 step 1).* A client that supplies documents (architecture §15) adds no sub-processor and no new data flow: its files are stored and indexed on our Scaleway Instance in Paris, and excerpts are sent in prompts to the same providers as public-source excerpts, OpenRouter and its upstream vendors only where that client has accepted external models. In the customer-facing list, "data received" reads "prompt contents, which may include excerpts of documents you supplied" for every model provider.

## Change log

| Date | Change |
| --- | --- |
| Oct 19, 2026 | First draft (P1a-15) |
| Oct 22, 2026 | DRAFT: client-supplied documents, no new sub-processor (P1b-19 step 1) |
