# Sub-processor List

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 19, 2026 |
| Author | Drafted for owner review (spec item P1a-15) |
| To finalise, the owner must | (1) confirm each DPA is accepted and record its reference in `paperwork-checklist.md`; (2) obtain Scaleway's written zero-retention confirmation for Generative APIs (findings M2); (3) replace the "pending verification" locations for AWS and Azure with the result of the TIA verification (findings C32); (4) set the "date added" to the date each service first receives client personal data; (5) publish the customer-facing version with the trust page. |

Method: built from `config/models.toml` (allow-list, provider sections, catalogue), `infra/` (Compose files, Authentik SMTP settings, Caddy) and the Stack Decision. Every outbound host the API and workers reach is in `[allow_list]`; the API refuses to start otherwise.

## Active sub-processors

| Sub-processor | Service | Purpose | Data received | Location | Safeguard | When used | Date added |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Scaleway SAS (France) | Instances, Block Storage, Private Network; Object Storage for backups (Phase 1b) | Hosting the API, web app, database, Redis, RAGFlow index, the download content store, logs and backups | All platform data, encrypted at rest | Paris, France (fr-par) | EU processing; Scaleway DPA **[reference, date accepted]** | Always | [date] |
| Scaleway SAS | Generative APIs (`api.scaleway.ai`), models `deepseek-v4.1-flash`, `qwen3.8-27b` | Default language-model inference, query rewrite | Prompt contents (system prompt, workspace instructions, public-source chunks, conversation turns, question); no identifiers | Paris, France | EU processing; Scaleway DPA; written zero-retention confirmation naming organisation, models and endpoint **pending** (findings M2); provider prompt-caching treatment to confirm | Every tenant | [date] |
| Mailgun Technologies, Inc. (Sinch), EU region | Transactional email: SMTP relay `smtp.eu.mailgun.org` for Authentik's sign-in links; HTTP API `api.eu.mailgun.net` for the platform's own mail (invitations, operator notices; Phase 1b) | Sending single-use sign-in links and platform mail | Recipient email address, the link, and Mailgun's delivery logs (retention per Mailgun EU plan; click and open tracking switched off) | EU region (Mailgun EU data centres) | Mailgun DPA with SCCs for any US-parent access **[reference, date accepted]**; EU region pinned in configuration (owner decision Oct 19, 2026) | Every tenant with sign-in links on (default) | [date] |

## Sub-processors for the optional external-models mode

Used only for a tenant whose signed acceptance is on file and for which the operator has enabled external models. Default off.

| Sub-processor | Service | Purpose | Data received | Location | Safeguard | Date added |
| --- | --- | --- | --- | --- | --- | --- |
| OpenRouter, Inc. (United States) | OpenAI-compatible API, EU endpoint `eu.openrouter.ai` | Routing prompts to the pinned upstream vendor | Prompt contents as above; our API key; no identifiers, no `user` field | Company: United States. API endpoint: EU (hosting location to verify) | OpenRouter DPA with SCCs, module [2/3] **[reference, date]**; TIA (`transfer-impact-assessment.md`); ZDR routing and `data_collection: deny` on every request | [date] |
| Amazon Web Services (Bedrock), upstream of OpenRouter | Inference for `anthropic/claude-opus-5.5` (pinned, no fallback) | Model inference | Prompt contents | **Pending verification:** eu-west-1 (Ireland) per the owner; fallback assumption United States | OpenRouter flow-down terms; on OpenRouter's ZDR list (to verify); SCCs and TIA | [date] |
| Microsoft (Azure), upstream of OpenRouter | Inference for `openai/gpt-6.1-sol` (pinned, no fallback) | Model inference | Prompt contents | **Pending verification:** an EU region per the owner (not named); fallback assumption United States | OpenRouter flow-down terms; on OpenRouter's ZDR list and free of prompt-retaining abuse monitoring (to verify); SCCs and TIA | [date] |

## Configured but not active

| Service | Status |
| --- | --- |
| Mistral AI (`api.mistral.ai`, Paris) | In the allow-list and `[mistral]` config, inactive since Phase 0 (`[llm] provider = "scaleway"`, findings M2). Not a sub-processor until activated; add here with notice to clients before first use. Web-search mode (Phase 2) depends on it. |

## Reviewed and not sub-processors

| Service | Why not |
| --- | --- |
| RAGFlow (Elasticsearch, MySQL, MinIO-compatible store, Valkey, TEI embedding model `bge-m3`) | Self-hosted on our Scaleway Instance on the private Compose network; no public listener, no external calls (it is configured with no LLM of its own, findings R11) |
| Authentik | Self-hosted on our Instance; sends mail through Mailgun's EU SMTP relay (listed above) |
| PostgreSQL, Redis, Caddy | Self-hosted on our Instance |
| Prometheus, Grafana, Loki (Phase 1b) | Self-hosted; "no SaaS APM that receives bodies" (architecture §9) |
| Container registries (Docker Hub, GitHub Container Registry) | Images are pulled; no platform data is sent |
| Certificate authority used by Caddy for TLS | Receives only our public hostname |
| GitHub (source code, CI) | Holds code and synthetic fixtures only; no client data, real queries or secrets (CLAUDE.md) |
| Public websites fetched by the crawler | We fetch from them; they receive no client data |

## Change log

| Date | Change |
| --- | --- |
| Oct 19, 2026 | First draft (P1a-15) |
