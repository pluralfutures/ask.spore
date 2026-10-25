# Data Protection Impact Assessment — Platform — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Revision | Oct 22, 2026, **DRAFT**: client-supplied documents (P1b-19 step 1, architecture §15): scope note in §1, risks R12 to R14, review trigger |
| Placeholders | [Client], [date] |
| To finalise, the owner must | (1) confirm the scope in §1 and the risk ratings in §5; (2) decide the open points in §8; (3) ask the DPO or privacy contact for advice and record it (Art. 35(2)); (4) have counsel review; (5) sign §9; (6) set the review date. |

---

## 1. Why we do a DPIA, and its scope

We index published sources that name people, at a scale that is not small, and we use AI models to answer questions from them. Clients' users type research questions that can reveal what their company is working on and may name people. The compliance guide advises a DPIA for this mix (large-scale processing of public personal data plus new technology). It is kept short and focuses on data-subject rights and accuracy, as the guide says.

*DRAFT addition, Oct 22, 2026:* the design for client-supplied documents (architecture §15, not built) is assessed in R12 to R14 below; for those documents we are processor and this DPIA supports the supplying client's own assessment. The test client supplies none.

Scope: the platform as built on Oct 21, 2026 (Phase 1a, single Instance in Paris), plus the Phase 1b changes that affect personal data (SSO, consent gate, platform mail, purge job, content console, crawl management). Two roles are covered:

- **Controller**, for the corpus and our own logs (`records-of-processing.md` Part 1).
- **Processor**, for clients' user data. Here this DPIA supports the client's own assessment (DPA clause 8.3); the client remains responsible for its DPIA.

## 2. Description of the processing

| Step | What happens | Where |
| --- | --- | --- |
| Corpus building | Our team registers published PDFs, crawled public pages and our own analysis; files are parsed, chunked and embedded in RAGFlow | Scaleway Instance, Paris |
| Sign-in | A user asks for a link; Authentik emails a single-use link through Scaleway Transactional Email (fr-par); SSO from Phase 1b (P1b-07) | Paris |
| Question | The API retrieves passages from the workspace's datasets (chosen server-side), builds a prompt with no identifiers and calls a model | Scaleway Generative APIs, Paris; external models only if enabled |
| Answer | Streamed with citations; stored with the conversation for at most 30 days | PostgreSQL, Paris |
| Downloads | Only files flagged `downloadable`; single-use 60-second link; 50 per user per day; audited | Paris |
| Audit | Append-only events with metadata, never text, 12 months | Paris |

Data categories, subjects and recipients are in `records-of-processing.md`.

## 3. Necessity and proportionality

- **Purpose.** Cited research answers for business clients. The corpus has to contain the sources as published to be useful; names of authors and executives are part of what makes a source citable.
- **Minimisation.** Prompts carry no tenant, user or package identifiers (tested). Logs hold metadata only (tested, ErrorBoundary since e0435c1). Clients upload no documents. Only excerpts reach the model, capped at 6,000 tokens.
- **Retention.** Conversations 30 days maximum; administrators can shorten to 1 day today and to 0 from Phase 1b (P1b-14). Audit 12 months.
- **Legal basis.** Corpus: legitimate interests (`legitimate-interest-assessment.md`). Client data: the client's instructions under the DPA.
- **Transparency.** Public privacy notice with an Art. 14 section (`privacy-notice.md`); AI notice in the UI; transparency note (`ai-transparency-note.md`); first-login notice from Phase 1b (P1b-10).
- **Rights.** Objection and erasure for people in the corpus within 30 days; takedown within 10 working days with an SLA timer from Phase 1b (P1b-03). Client users exercise rights through their employer (DPA clause 8).
- **Processors.** Scaleway under its DPA in Paris; external models only after the paperwork gate (`paperwork-checklist.md`).

## 4. Risks to people

Likelihood and severity on a 1 to 3 scale; risk = likelihood × severity, before measures.

### People named in the corpus

| # | Risk | L | S | Risk |
| --- | --- | ---: | ---: | ---: |
| R1 | **Inaccurate or decontextualised statements.** The model attributes a statement to the wrong person, merges two people, or presents an old or out-of-context quote as current | 2 | 2 | 4 |
| R2 | **Cannot object or be forgotten.** A person does not know they are in the corpus, or their request is not found in all copies (index, cache, stored citations) | 2 | 2 | 4 |
| R3 | **Special-category data surfaces.** A crawled page contains health, political or similar data about a named person, and answers repeat it | 1 | 3 | 3 |
| R4 | **Profiling.** Users query the corpus to build a profile of an individual | 1 | 2 | 2 |

### Clients' users

| # | Risk | L | S | Risk |
| --- | --- | ---: | ---: | ---: |
| R5 | **Cross-tenant leakage.** One client sees another's questions, answers or cached answers | 1 | 3 | 3 |
| R6 | **Query confidentiality at vendors.** A model provider retains or uses prompts | 1 | 2 | 2 |
| R7 | **Transfer outside the EEA** in the external-models mode (US-law access) | 1 (mode off) | 2 | 2 |
| R8 | **Retention longer than promised.** Expired conversations remain in the database or backups | 3 (today) | 1 | 3 |
| R9 | **Mailbox takeover gives account access.** Anyone who controls a user's mailbox can sign in by link; a mail scanner could consume a link | 2 | 2 | 4 |
| R10 | **Body text in logs or errors** exposes questions to operators | 1 | 2 | 2 |
| R11 | **Personal data typed into questions**, including about third parties, is sent to the model | 2 | 1 | 2 |
| R12 | **Client-supplied document reaches another client** (placed in a shared tag or another tenant's workspace, merged by de-duplication) and its contents, including people named in it, are shown to the wrong customer. *DRAFT, Oct 22, 2026* | 1 | 3 | 3 |
| R13 | **More personal data than declared in client files** (staff data, special categories), indexed and sent to the model. *DRAFT* | 2 | 2 | 4 |
| R14 | **Client file not removed** on withdrawal or termination (a copy left in a dataset, the content store or a cache). *DRAFT* | 1 | 2 | 2 |

## 5. Measures and residual risk

| Risk | Measures built (Oct 21, 2026) | Measures planned | Residual |
| --- | --- | --- | --- |
| R1 | Every answer cites its passages with publisher, title, date and page; in corpus-only mode an answer that cites nothing is withheld (G6); the prompt keeps each passage's statement in its own sentence (corpus_only/v5); "AI-generated, verify against cited sources" notice; eval set and guardrail eval gate on prompt changes | Eval gate in CI (P1b-15); feedback review | Low–medium. Model error cannot be ruled out; the citation lets the user check |
| R2 | Public privacy notice with contact; source register lists every source; manual withdrawal by an operator | Withdrawal cascade over every dataset, the answer cache and stored citations, with audit (P1b-03); takedown queue with timer (P1b-03); request log | Medium until P1b-03, then low |
| R3 | Sources chosen by our team; `noindex`/`noai` pages skipped | Crawl-time special-category path filter with reviewer whitelist (P1b-04); approval before ingestion (P1b-01) | Low after P1b-04 |
| R4 | Corpus is business and sector material; terms forbid profiling of individuals (`terms-of-service.md`); no person search feature | Bulk-extraction detection (not scheduled) | Low |
| R5 | RLS forced on all 18 tenant tables; tenant-prefixed cache keys; isolation tests including negative cases; independent review (findings §12) | Isolation tests for new Phase 1b tables (P1b-16) | Low |
| R6 | Scaleway default; ZDR routing and `data_collection: deny` asserted on every OpenRouter request; no identifiers | Scaleway written zero-retention confirmation (pending, M2) | Low once M2 is on file |
| R7 | Mode off for every tenant; opt-in only after signed acceptance; picker says "served outside the EU"; spend cap | TIA verification (C32), DPA with SCCs | Low; mode not in use |
| R8 | Read-time expiry: expired conversations are unreachable from every route (tested); cap of 30 enforced in the database | Purge job (P1b-14); backup retention 30 days with object lock (owner-run) | Medium until P1b-14, then low |
| R9 | Single-use, 15-minute, browser-bound links consumed only by a POST from the landing page; 5 links per user per window; no enumeration | Client SSO (P1b-07); admin MFA (P1b-08); per-IP rate limit (P1b-08); links switched off per tenant once its SSO is live, unless the operator enables them for that tenant (P1b-06; owner decision Oct 21, 2026) | Medium for link-only tenants; low with SSO |
| R10 | Logging allow-list with static check; ErrorBoundary; `hide_parameters=True`; control characters refused | Same rules for the worker (P1b-02) | Low |
| R11 | No identifiers added by us; ZDR; terms tell users not to enter special-category data | First-login notice (P1b-10) | Low |
| R12 | Dataset IDs resolved server-side; forced RLS; out-of-package chunks dropped; tenant-prefixed cache | Tenant-owned tags with the placement rule checked by API, worker and database; per-owner de-duplication; negative CI tests (P1b-19 step 2, architecture §15.4) | Low once step 2 ships; clause 7A not offered before |
| R13 | — | Client declaration per batch; reviewer check before ingestion; DPA clause 7A.1 bars special categories unless agreed; client is controller (Art. 14 is its duty) | Medium; depends on the client |
| R14 | Withdrawal cascade (P1b-03) | Content-store copies per tenant; termination purge step and certificate figures (P1b-19 step 2 with P1b-14) | Low |

## 6. Data-subject rights in practice

| Right | People in the corpus (we are controller) | Clients' users (client is controller) |
| --- | --- | --- |
| Information | `privacy-notice.md` Art. 14 section | `privacy-notice.md` and the client's own notice; first-login notice from P1b-10 |
| Access | We search the source register and corpus for the name and reply within one month | Forwarded to the client (DPA 8.1) |
| Rectification | Correct our own analysis; for third-party sources, remove or redact (we do not edit publishers' text) | Forwarded |
| Erasure / objection | Remove the document or ingest a redacted copy within 30 days; record the decision | Client deactivates or asks us to delete (DPA 8.2) |
| Restriction | Withdraw the source pending the decision | Forwarded |

## 7. Prior consultation (Art. 36)

Not required, in our view. After the measures in §5 no risk is rated high. The highest residual risks (R2, R8, R9) are medium only until named Phase 1b items ship, and the external-models transfer is not in use. The owner should repeat this conclusion after Phase 1b. Counsel to confirm against the the AEPD (Spain)'s DPIA list.

## 8. Open points for the owner

1. Whether to hold back the first client's production use until P1b-03 (withdrawal cascade) and P1b-14 (purge) are live, or accept the medium residual risk for R2 and R8 in the meantime.
2. Sign-in links once SSO is live (R9): decided by the owner on Oct 21, 2026. They are switched off for a tenant when its SSO connection goes live, unless the operator specifically enables them for that tenant.
3. Whether the downloadable flag on third-party test-corpus rows (owner decision Oct 20, 2026) is backed by a recorded licence basis per source; a wrong flag is a licensing risk more than a privacy one, recorded in `risk-register.md`.

## 9. Sign-off

| | Name | Date | Notes |
| --- | --- | --- | --- |
| Measures approved by | [ ] | [ ] | |
| Residual risks accepted by | [ ] | [ ] | |
| DPO or privacy contact advice | privacyanddata@myceliumgastronomy.com | [ ] | Summarise the advice and whether it was followed |
| Counsel reviewed | [ ] | [ ] | |

## 10. Review

Review by [date], and at once when: external models are enabled for any tenant; the first client supplies documents (architecture §15); web-search mode (Phase 2) or tenant-edited prompts (Phase 2) start; a new data category enters the prompt; a new sub-processor is added; a client uses outputs for decisions about individuals (also see `ai-act-technical-documentation.md`); a personal data breach occurs.
