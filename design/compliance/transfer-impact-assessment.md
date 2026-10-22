# Transfer Impact Assessment — External Models (OpenRouter, Amazon Bedrock, Microsoft Azure)

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 19, 2026 |
| Author | Drafted for owner review (spec item P1a-15) |
| Applies to | The "external models" entitlement: `anthropic/claude-opus-5.5` and `openai/gpt-6.1-sol` through OpenRouter (`config/models.toml`) |
| Review date | **[date]**, no later than the start of the SOC 2 observation window, and earlier on any trigger in §9 |
| To finalise, the owner must | (1) fill in the SCC module and version and the OpenRouter DPA reference in §5; (2) have P1a-16 complete the verification in §10 and record which of §4A or §4B applies; (3) confirm the GDPR roles position in §2 (pending, see `client-dpa-draft.md`); (4) set the review date; (5) sign and date §11. Until then the entitlement stays off for every tenant (`paperwork-checklist.md`). |

## 1. What is transferred and why

A tenant with the operator-set external-models entitlement lets its users pick Claude Opus 5.5 or GPT-6.1 Sol for a conversation. Each answer is one API call from our API (Scaleway, Paris) to OpenRouter's EU endpoint `https://eu.openrouter.ai/api/v1`, which forwards the prompt to the one upstream vendor pinned for the model. The answer streams back the same way. Everything else (hosting, index, storage, logs, backups, download content store, chat history) stays on Scaleway in Paris and is outside this assessment.

## 2. Parties and roles

| Party | Role for the prompt contents | Contract |
| --- | --- | --- |
| [Client] (the tenant) | Controller of its users' questions and conversations | Client DPA (`client-dpa-draft.md`) |
| Estefania Simon-Sasyk y Otro CB (we) | Processor for the client's user data; controller for the public-corpus chunks in the prompt (roles position confirmed by the owner, Oct 20, 2026) | — |
| OpenRouter, Inc. (United States) | Our sub-processor; routes the request | OpenRouter DPA with SCCs, §5 |
| Amazon Web Services (Bedrock), for Claude | OpenRouter's sub-processor (upstream vendor) | Between OpenRouter and AWS; checked against OpenRouter's published upstream list |
| Microsoft (Azure), for GPT-6.1 Sol | OpenRouter's sub-processor (upstream vendor) | Between OpenRouter and Microsoft; same check |

One prompt carries data under both of our roles: the question and conversation turns (we are processor, so processor-to-processor SCCs, module 3) and retrieved chunks of public sources, which may name authors or quoted people (we are controller, so controller-to-processor SCCs, module 2). The OpenRouter DPA must cover both modules, or the owner records why one suffices.

## 3. Data in scope

Sent: the platform system prompt (fixed text, with the workspace's tenant-authored additional-instructions block in its delimited section), retrieved public-corpus chunks with provenance (publisher, title, date, page), the last conversation turns (at most 6 messages and about 2,000 tokens), and the user's question. Returned: the answer text (reasoning text is discarded, never stored).

Not sent: tenant, user, workspace, package or dataset identifiers; email addresses; the `user` field or attribution headers (findings C10); client documents (clients upload nothing). The prompt-content tests prove the code adds no identifiers (P1a-06, P1a-10).

Personal data that can still be present: names or facts a user types into a question; names in public sources; tenant or staff names a tenant admin writes into the additional-instructions block (permitted tenant-authored exception, flagged to the operator, compliance addendum Oct 18). No special-category data is expected; it is not filtered either.

Volume: one test client, three workspaces, external spend capped at EUR 30 per month with a hard stop (P1a-10), which at the catalogue prices (about 7,000 tokens in and 1,000 out per answer) is roughly 600 Claude or 1,200 GPT answers a month.

Metadata OpenRouter and the vendor see: our API key, our server's IP address, model, token counts, timestamps.

## 4. Destination countries

OpenRouter: contracting entity in the United States; the API hop terminates at the EU endpoint. Where `eu.openrouter.ai` is hosted, and whether US staff or systems can access requests in flight, is **to verify** (§10). Treat OpenRouter as a US-law entity in either case.

### 4A. With the pins honoured (claim pending verification, findings C32)

| Model | Pinned provider | Region stated by the owner | Country |
| --- | --- | --- | --- |
| `anthropic/claude-opus-5.5` | `amazon-bedrock`, `allow_fallbacks = false` | eu-west-1 | Ireland |
| `openai/gpt-6.1-sol` | `azure`, `allow_fallbacks = false` | "EU region" (not named) | [EU country, to fill in] |

Our client pins the **provider only**; no region field is sent, because OpenRouter's provider-routing documentation could not be read from the build container (findings C31). Whether OpenRouter's `amazon-bedrock` and `azure` endpoints for these slugs serve from the EU, and whether a region can be requested at all, is **unverified**. If 4A holds, processing is in the EU by US-parent vendors: still a restricted transfer to OpenRouter, and a residual US-law access exposure through all three parent companies.

### 4B. Fallback: pins do not fix the region (applies if verification fails or is inconclusive)

Assume processing in the **United States** (default regions of both vendors), possibly other vendor regions. This is the analysis the entitlement relies on until §10 is complete, and it is written so that it is sufficient on its own.

## 5. Transfer mechanism

- OpenRouter DPA incorporating the EU Standard Contractual Clauses (Commission Implementing Decision (EU) 2021/914), module **[2 and/or 3]**, version/date **[ ]**, accepted on **[date]**, filed at **[location]**.
- Onward transfers to AWS and Microsoft: under OpenRouter's flow-down terms, per its DPA; OpenRouter's published upstream list and retention terms checked on **[date]**.
- EU–US Data Privacy Framework: if OpenRouter, AWS and Microsoft are certified (to check on the DPF list and record the date), the transfer to each also rests on the adequacy decision of July 10, 2023, upheld by the General Court in September 2025 (appeal possible). The SCCs remain the primary mechanism here so that the assessment does not depend on the framework surviving.

## 6. Laws of the destination (United States, fallback 4B)

Relevant: FISA Section 702 (all three are likely "electronic communication service providers"), Executive Order 12333 (collection in transit, outside US territory), and the CLOUD Act (compelled production of data in a provider's control, wherever stored, which also covers EU-hosted processing by these US companies in 4A). Mitigating: EO 14086 and the Data Protection Review Court; the providers' published practice of challenging overbroad requests and transparency reporting.

Assessment for this data: prompts are business research questions about public market and sector information, plus public-source text. They are not communications of a target likely to interest US intelligence, carry no identifiers linking them to a client or user, and under zero-data-retention routing are not held at rest, so a CLOUD Act order against stored data has nothing to reach. The realistic exposure is interception in transit or during the seconds of processing, which TLS and the absence of identifiers limit. Commercial sensitivity (what the client is researching) is the main harm, and it is a confidentiality risk more than a fundamental-rights one.

## 7. Supplementary measures

| Measure | Where it is enforced |
| --- | --- |
| Zero-data-retention routing (`provider.zdr = true`) on every request, set last so nothing overrides it | `app.llm.openrouter`, tested (findings C10, C31) |
| `provider.data_collection = "deny"` on every request | Same, tested |
| EU endpoint `eu.openrouter.ai`, the only external host on the allow-list; startup refuses `openrouter.ai` hosts | `config/models.toml`, tested (findings C25) |
| Provider pins with fallbacks off (Bedrock for Claude, Azure for GPT) | Catalogue `provider_order`, `provider_only` (findings C31) |
| No tenant, user, workspace, dataset identifiers; no `user` field or attribution headers | Prompt builder and client, tested |
| No client documents; only capped retrieved chunks (6,000 tokens) | Clients upload nothing; `[chat] max_context_tokens` |
| No tools, no plugins, no `:online` variants, no `openrouter/auto` | Client refuses unpinned slugs |
| Per-tenant opt-in with signed acceptance reference on file; default off | Operator console, check constraint (findings A13) |
| Spend cap EUR 30/month with hard stop and fallback to an EU model | `usage_ledger`, P1a-10 |
| Chat history 30 days maximum on our side (1 to 30 per tenant); metadata-only logs | `tenant_settings`, logging allow-list |
| Users see on the model picker that external models are served outside the EU | Web app |

## 8. Residual risk

- **US-law access** to prompts in transit or in processing: low likelihood, moderate impact (client research intent). Accepted given §6 and §7.
- **Upstream vendor retention outside ZDR** (for example abuse-monitoring logging on Azure, which by default can retain prompts unless the deployment has an exemption): open until §10 item 4 is confirmed. If not confirmed, remove the slug or accept and disclose in writing.
- **Region not honoured** (4B): covered by this assessment; disclosed to the client as "served outside the EU".
- **Free-text personal data typed by users**: not technically preventable; covered by the DPA and the picker notice.
- **Provider or terms change** (OpenRouter list, vendor, ZDR policy): review triggers below.

Conclusion (subject to §10 and the owner's sign-off): with the SCCs in place and the measures in §7, the transfer offers protection essentially equivalent to the EU for this data, under 4A and under the fallback 4B.

## 9. Review

Review by the review date above, and immediately when: a slug or pin changes; OpenRouter changes its DPA, ZDR policy or upstream list; a vendor's region or retention terms change; the DPF status changes; a second tenant is enabled; the prompt starts carrying a new data category.

## 10. Verification P1a-16 must complete

Each item records the date, who checked, and where the evidence is kept (see `paperwork-checklist.md`).

1. From OpenRouter's provider-routing documentation: whether a request can pin a **region**, not only a provider; the exact field, and whether the EU endpoint restricts routing to EU regions by itself.
2. One real request per external model through `eu.openrouter.ai`, with the production request shape: record the provider metadata OpenRouter returns (serving provider, and region if reported). Synthetic prompt only.
3. That `amazon-bedrock` for `anthropic/claude-opus-5.5` serves from eu-west-1, and `azure` for `openai/gpt-6.1-sol` serves from a named EU region; fill the country into §4A.
4. That both pinned endpoints are on OpenRouter's published zero-data-retention list, and that the Azure endpoint is not subject to prompt-retaining abuse monitoring.
5. Where `eu.openrouter.ai` is hosted and whether OpenRouter retains any request content or only metadata.
6. DPF certification status of OpenRouter, AWS and Microsoft on the date checked.
7. Outcome: state "4A verified" or "4B applies" in this document and in the trust page.

## 11. Sign-off

| | Name | Date |
| --- | --- | --- |
| Owner | [ ] | [ ] |
| Counsel reviewed (optional) | [ ] | [ ] |
