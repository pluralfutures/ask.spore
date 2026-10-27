# Sub-processor List

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 19, 2026 |
| Author | Drafted for owner review (spec item P1a-15) |
| Revision | Oct 22, 2026, **DRAFT**: client-supplied documents (P1b-19 step 1, architecture §15) add no sub-processor; the data received by Scaleway and, if enabled, the external-models chain widens |
| To finalise, the owner must | (1) record the acceptance date of the Scaleway DPA (version of June 1, 2024) and the acceptance of the OpenRouter DPA (version of Aug 26, 2026, signed Oct 23, 2026) in `paperwork-checklist.md`, and resolve the points under "DPA review notes" below; (2) keep a dated copy of Scaleway's published zero-retention policy (Scaleway issues no letter; findings M2); (3) verify the AWS and Azure region constraint with one real request each (findings C32); (4) set the "date added" to the date each service first receives client personal data; (5) publish the customer-facing version with the trust page. |

Method: built from `config/models.toml` (allow-list, provider sections, catalogue), `infra/` (Compose files, Authentik SMTP settings, Caddy) and the Stack Decision. Every outbound host the API and workers reach is in `[allow_list]`; the API refuses to start otherwise.

## Introduction (customer-facing text)

*DRAFT, Oct 27, 2026. Adapted from the form of Scaleway's published sub-processor page. Aligned with client DPA clauses 5.1 to 5.3 and `policy-vendor-management.md`; the [30] days is the same placeholder as in the DPA. Publish this text above the customer-facing list; the working notes elsewhere in this file stay internal.*

To provide ask.spore, we use third-party service providers that may process personal data on our customers' behalf. This page tells our customers which sub-processors are likely to process their personal data as part of the service, in line with our Data Processing Agreement (DPA) and our Privacy Notice.

Each sub-processor is reviewed for security and data protection before it receives any customer data, and we hold it to data protection obligations no less protective than those in our DPA. We stay responsible to our customers for how our sub-processors perform. Our language-model providers are also bound by zero-data-retention terms, so prompts and answers are not kept or used for training. Our systems can only reach providers on an approved list, and an external (non-EU) provider is used only for a customer that has accepted it in writing.

**Authorisation to engage new sub-processors**

By using ask.spore and agreeing to our DPA, the customer gives us general authorisation to engage the sub-processors listed here. We will give the customer at least [30] days' written notice before adding or replacing a sub-processor, and this page will be updated at the same time. The customer may object on reasonable data-protection grounds within that period. If we cannot agree a solution, the customer may end the affected part of the service without penalty.

## Active sub-processors

| Sub-processor | Service | Purpose | Data received | Location | Safeguard | When used | Date added |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Scaleway SAS (France) | Instances, Block Storage and snapshots, Private Network, Secret Manager; Object Storage for backups (Phase 1b) | Hosting the API, web app, database, Redis, RAGFlow index, the download content store, logs, backups and deployment secrets | All platform data, encrypted at rest; for clients that supply documents (DRAFT, Oct 22, 2026), their documents, parsed text and index | Paris, France (fr-par) | EU processing; Scaleway DPA, version of June 1, 2024 (entered into; acceptance date to record) | Always | [date] |
| Scaleway SAS | Generative APIs (`api.scaleway.ai`), models `deepseek-v4.1-flash`, `qwen3.8-27b` | Default language-model inference, query rewrite | Prompt contents (system prompt, workspace instructions, public-source chunks and, for clients that supply documents, excerpts of their documents, conversation turns, question); no identifiers | Paris, France (the policy names Paris as the storage region; models hosted on Scaleway's own infrastructure in Europe, no third-party services) | EU processing; Scaleway DPA; Scaleway's published zero-retention policy for Generative APIs ("Understand the Generative APIs Privacy Policy", version of Oct 3, 2025, https://www.scaleway.com/en/docs/generative-apis/reference-content/data-privacy/); Scaleway issues no written confirmation, so the published policy is the evidence (owner, Oct 26, 2026; findings M2; dated copy in `evidence/`). Per the policy: no use of prompts or outputs for training, no access for model creators or other customers; prompt caching holds no prompt text (prefix hashes and KV values only, ephemeral, isolated per project, cannot be switched off); exception: a request that causes errors or looks malicious may be stored and read for up to two weeks | Every tenant | [date] |
| Scaleway SAS | Transactional Email, region fr-par: SMTP relay `smtp.tem.scw.cloud` for Authentik's sign-in links; HTTP API for the platform's own mail (invitations, operator notices; Phase 1b) | Sending single-use sign-in links and platform mail | Recipient email address, the link, and the service's delivery logs (email content is deleted as soon as processing ends: when the recipient server accepts it, at the first hard bounce, or after 36 hours of failed attempts; spam-classified email after 72 hours, email held by a blocked domain after 15 days, encrypted backups kept 7 days; sending metadata, logs and activity history are kept while the sending domain is active, and Scaleway plans to shorten this in 2027; webhook data 15 days; no link rewriting) | Paris, France (fr-par) | EU processing; covered by the Scaleway DPA above (owner decision Oct 20, 2026) | Always | [date] |
| Mailgun Technologies, Inc. (Sinch), EU region — **optional backup, not active** | Transactional email: SMTP relay `smtp.eu.mailgun.org`, HTTP API `api.eu.mailgun.net`; activated only by configuration if Scaleway Transactional Email is unavailable | Sending single-use sign-in links and platform mail while active | Recipient email address, the link, and Mailgun's delivery logs (retention set to the shortest available; click and open tracking switched off) | EU region (Mailgun EU data centres) | Mailgun DPA with SCCs for any US-parent access **[reference, date accepted]**, filed before activation; EU region pinned in configuration (owner decisions Oct 19 and Oct 20, 2026) | None while inactive | [date] |

## Sub-processors for the optional external-models mode

Used only for a tenant whose signed acceptance is on file and for which the operator has enabled external models. Default off.

| Sub-processor | Service | Purpose | Data received | Location | Safeguard | Date added |
| --- | --- | --- | --- | --- | --- | --- |
| OpenRouter, Inc. (United States) | OpenAI-compatible API, EU endpoint `eu.openrouter.ai` | Routing prompts to the pinned upstream vendor | Prompt contents as above; our API key; no identifiers, no `user` field | Company: United States. API endpoint: EU. Under Exhibit A of its DPA (EU-only processing; confirm it is elected for our account), prompts and answers are processed only in EU/EEA infrastructure; account data, billing and security logs are not covered and may be outside the EU (its own hosting is Google Cloud, US regions) | OpenRouter DPA, version of Aug 26, 2026, signed Oct 23, 2026, with EU SCCs Module 2 as drafted (Irish law, Dublin courts; see the module point below); TIA (`transfer-impact-assessment.md`); ZDR routing and `data_collection: deny` on every request | [date] |
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
| Squarespace Domains LLC (domain registration and DNS for `myceliumgastronomy.com`, including the `askspore` host and the SPF, DKIM, MX and DMARC records for sending) | **DRAFT, Oct 27, 2026; owner to confirm.** Holds our registrant details and DNS records, which are not client data. Answers DNS lookups for our hostnames, so it sees the IP address of the resolver that asks, not the content of any request, query or email. No client or user personal data is sent to it. Turn this into an active entry if counsel advises that DNS query logs make it a processor |
| Container, package and image registries (Docker Hub, GitHub Container Registry, Microsoft Container Registry, PyPI, npm) | Images and packages are pulled at build and deploy time; no platform data is sent |
| Let's Encrypt (certificate authority used by Caddy for TLS) | Receives only our public hostname |
| Microsoft Entra ID and Google Workspace as a tenant's own sign-in source | The client's own identity provider, chosen and contracted by the client. Our Authentik receives the sign-in result; we send these providers nothing |
| Google Workspace mailboxes of the operator (`daniel@`, `security@myceliumgastronomy.com`) | **Owner to confirm.** Ordinary company mail, not the platform. Not a processing route for client data unless a client emails us personal data or a security reporter does; then it is incidental, and the incident runbook says what to do |
| GitHub (source code, CI) | Holds code and synthetic fixtures only; no client data, real queries or secrets (CLAUDE.md) |
| Public websites fetched by the crawler | We fetch from them; they receive no client data |

## Client-supplied documents

*DRAFT, Oct 22, 2026 (P1b-19 step 1).* A client that supplies documents (architecture §15) adds no sub-processor and no new data flow: its files are stored and indexed on our Scaleway Instance in Paris, and excerpts are sent in prompts to the same providers as public-source excerpts, OpenRouter and its upstream vendors only where that client has accepted external models. In the customer-facing list, "data received" reads "prompt contents, which may include excerpts of documents you supplied" for every model provider.

## DPA review notes (Oct 27, 2026; internal, owner and counsel)

From the Scaleway DPA (version of June 1, 2024) and the OpenRouter DPA (last updated Aug 26, 2026).

1. **Notice we are promised is not automatic.** Scaleway gives 30 days' notice of a sub-processor change only if we have subscribed to updates on its sub-processor page (art. 7.4). OpenRouter does the same only if we email support@openrouter.ai, and **excludes AI model providers** (Amazon, Microsoft) from that notice (s. 5.2). Our client DPA promises [30] days for every sub-processor (clause 5.2). Do both subscriptions and note the date in the checklist. For OpenRouter's upstream vendors, our own pinned routing (`provider_only`, no fallback) is the control; check trust.openrouter.ai at each annual review.
2. **SCC module.** OpenRouter's DPA treats the customer as the controller, so its SCCs are Module 2 (controller to processor). We are a processor for our clients, which is Module 3 (processor to processor). Ask OpenRouter to confirm Module 3 or accept an amendment, or have counsel confirm Module 2 is enough. Update `transfer-impact-assessment.md` once decided.
3. **EU-only addendum.** Exhibit A applies only if EU-only processing is elected in an order form or written agreement. Confirm it for our account in writing. It covers prompts and answers only, and says "EU or EEA" where this list says "EU, EEA, UK or Switzerland"; align the wording once the AWS and Azure region check (findings C32) is done.
4. **OpenRouter's own sub-processors** (its DPA names Google Cloud hosting, Cloudflare in front, Datadog for logs; the full list is at trust.openrouter.ai) handle prompts in transit. Read that list and add the ones that touch prompt contents to the external-models table, or record why not.
5. **Zero retention is narrower than our wording.** OpenRouter deletes payloads after each request, but may run automated risk classification first and may keep data where the law requires or to address misuse; it also states that a provider's ZDR listing is the provider's own policy, not OpenRouter's guarantee (s. 2.4). Keep the "on ZDR list (to verify)" caveats, and keep the trust page from saying "no retention" without them.
6. **Breach notice.** OpenRouter notifies within 72 hours; Scaleway "as soon as possible", no figure. Our client DPA says [48] hours (clause 9.1, open question B7). We cannot promise a window shorter than our slowest sub-processor's; move it to 72 hours or say "without undue delay".
7. **Scaleway's DPA says nothing on zero retention** for Generative APIs, only EU location by default (art. 11.1) and no transfer outside the EU without notice (art. 11.2.2). The published Generative APIs policy (version of Oct 3, 2025) is the evidence (findings M2). It answers the caching question (no prompt text kept) and names Paris. It is not absolute: on a request that triggers errors (it gives HTTP 500 as the example, about one in a million) or looks malicious, Scaleway may store and read the full request for up to two weeks. Say so in the privacy notice and trust page rather than "never stored"; our prompts carry no identifiers, which limits the exposure. The policy can change on its own page, so re-read it at each annual review and keep the dated copy.
8. **Audit rights are limited:** once a year at our cost, 30 days' notice with Scaleway (art. 12) and reasonable request with OpenRouter (s. 6). The client DPA clause 11 should not promise more than we can pass on.

## Change log

| Date | Change |
| --- | --- |
| Oct 19, 2026 | First draft (P1a-15) |
| Oct 22, 2026 | DRAFT: client-supplied documents, no new sub-processor (P1b-19 step 1) |
| Oct 27, 2026 | DRAFT: OpenRouter and Scaleway DPAs reviewed; OpenRouter version, SCC module and EU-only addendum recorded; notes added |
| Oct 27, 2026 | DRAFT: Squarespace (domain, DNS) reviewed and recorded as not a sub-processor, owner to confirm; Scaleway Secret Manager and snapshots named; registries, Let's Encrypt, tenant identity providers and operator mailboxes added to the reviewed list |
