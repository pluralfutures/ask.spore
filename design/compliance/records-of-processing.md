# Records of Processing Activities (GDPR Art. 30) — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Revision | Oct 22, 2026, **DRAFT**: client-supplied documents (P1b-19 step 1): C1 scope note, C9 (client declarations), and the Part 2 template row for clients that supply documents. Placeholders added: [limitation period]. Oct 25, 2026, **DRAFT** (P2A-10): time-boxed support access (P2A-08) in C4 and the Part 2 sheet |
| Placeholders | [Client], [Client legal name], [Client address], [date], [SCC module], [document store], [representative, if any] |
| To finalise, the owner must | (1) fill in the entity, contact and DPO placeholders; (2) decide whether a DPO is required (see open-questions.md) or name a privacy contact; (3) confirm the reasoning on the usage ledger in Part 1, row C5; (4) confirm the retention periods marked [confirm]; (5) add one Part 2 sheet per client at signature, starting with [Client]; (6) have counsel review; (7) review every six months and on every change to `sub-processors.md`. |

---

## How to read this record

We keep two registers, following the roles the owner confirmed on Oct 20, 2026:

- **Part 1, controller (Art. 30(1)).** Processing we decide on ourselves: the research corpus, our own operational and security logs, our operator accounts, requests sent to us, and our business contacts.
- **Part 2, processor (Art. 30(2)).** Processing we do for each client: its users' accounts, sign-in events, conversations, downloads and the audit of its users. One sheet per client.

The technical and organisational measures (TOMs) are described once, in `client-dpa-draft.md` Annex 2 and the policy set (`policy-information-security.md` and the other `policy-*.md` files). Rows below cite them as "TOMs".

Where a measure is not built yet, the row says so and names the spec item.

## Controller and contacts

| | |
| --- | --- |
| Controller | Estefania Simon-Sasyk y Otro CB, comunidad de bienes trading as Mycelium Gastronomy Network, NIF E19824093, Hermanos Otamendi kalea, 11, 20014 San Sebastián, Gipuzkoa, Spain |
| Privacy contact / DPO | privacyanddata@myceliumgastronomy.com |
| Takedown and data-subject requests about the corpus | security@myceliumgastronomy.com |
| Representative in the EU (Art. 27) | [representative, if any] — not needed if the entity is established in the EU |

---

## Part 1 — Controller register (Art. 30(1))

### C1. Public-source corpus (third-party PDFs and crawled web pages)

| Field | Entry |
| --- | --- |
| Purpose | Building and keeping a searchable research library from published sources, so that clients' users get cited answers |
| Legal basis | Legitimate interests, Art. 6(1)(f); see `legitimate-interest-assessment.md` |
| Data subjects | People named in published sources: authors, executives, people quoted, spokespeople |
| Categories of personal data | Names, job titles, employers, quoted statements, professional facts as published. Special categories are not sought; a crawl-time filter for obvious cases comes from Phase 1b (P1b-04) |
| Source of the data | Publishers' reports and public websites (Art. 14 applies; see `privacy-notice.md` §"People named in our sources") |
| Recipients | Clients' users, as excerpts with citations in answers; the language-model providers in `sub-processors.md` receive excerpts inside prompts |
| Transfers outside the EEA | Only when a client has the external-models mode enabled and a user picks an external model: excerpts in the prompt go via OpenRouter to AWS or Azure (`transfer-impact-assessment.md`). Off for every tenant today |
| Storage | RAGFlow index and file store on our Scaleway Instance in Paris; original files in the content store (`[files] content_root`) on the same Instance; source register in PostgreSQL |
| Retention | While the source is licensed and relevant. Removed on takedown or a successful objection. The withdrawal cascade (index, cache, stored citations flagged) comes from Phase 1b (P1b-03); until then withdrawal is a manual operator procedure |
| TOMs | Source register with licence basis; robots.txt, TDMRep and `noai`/`noindex` honoured by the crawler today, per-site decisions from P1b-04; downloads only for sources flagged `downloadable`; citations and excerpts, no full-document viewer; RAGFlow has no public listener |

Scope note (DRAFT addition, Oct 22, 2026 (P1b-19 step 1; architecture §15).): C1 covers platform-gathered sources only. Documents a client supplies for its own workspaces are processed as processor and recorded in that client's Part 2 sheet, not here; public content we add to supplement a client stays in C1.

### C2. Own analysis (DOCX and PPTX written by our team)

| Field | Entry |
| --- | --- |
| Purpose | Publishing our own research to clients through the library |
| Legal basis | Legitimate interests, Art. 6(1)(f) |
| Data subjects | Our authors; people named in our analysis (rare) |
| Categories | Author names; names and professional facts about people named |
| Recipients | Clients' users (excerpts, and downloads where the source is flagged `downloadable`) |
| Transfers | As C1 |
| Retention | Business need; reviewed on the source register review date |
| TOMs | As C1 |

### C3. Operational logs (application stdout)

| Field | Entry |
| --- | --- |
| Purpose | Running, debugging and securing the service |
| Legal basis | Legitimate interests, Art. 6(1)(f) (security and integrity of the service) |
| Data subjects | Clients' users and our operators, indirectly |
| Categories | Allow-listed metadata only: request ID, route, method, status, error code, latency, token counts, tenant ID and internal user UUIDs where logged. Never questions, answers, prompts, excerpts, headers, tokens, email addresses or request bodies (`app.core.logging`; unhandled errors reduced to one allow-listed line since e0435c1) |
| Recipients | Our operators only |
| Transfers | None |
| Storage | Container logs on the Scaleway Instance, Paris. A central log stack (Loki) is in the backlog, not built |
| Retention | [confirm: Docker log rotation setting on the Instance]; target 30 days |
| TOMs | Logging allow-list with static check (`test_logging_policy`), ErrorBoundary, access logs off in uvicorn and Caddy |

### C4. Platform audit under the internal tenant, and operator accounts

| Field | Entry |
| --- | --- |
| Purpose | Accountability for operator and content actions: tenant creation, entitlements, operator grants and revocations, source-register changes, downloadable flags, and operator reads through a client's support grant (P2A-08) |
| Legal basis | Legitimate interests (security, accountability) and Art. 5(2) and 24 GDPR |
| Data subjects | Our operators and internal users (today: the owner) |
| Categories | Operator account (email, name, Authentik identifier); audit events (`operator.*`, `ingest.*`, `auth.*`) with internal user UUID, time and before/after values of settings |
| Recipients | Our operators |
| Transfers | None |
| Storage | `audit_events` in PostgreSQL on the Instance; Authentik on the same Instance |
| Retention | Audit events 12 months. The table is append-only and a trigger refuses UPDATE and DELETE for every role, so the 12-month disposal needs a controlled procedure that is not yet written (`policy-data-retention-disposal.md`). The daily export to write-once storage is not built. Operator accounts: while the person is an operator, then deactivated |
| TOMs | Append-only audit table; operators granted only from the command line as schema owner; operator role cannot read conversations or messages (findings A12); support reads only through a client administrator's time-boxed grant, as a separate database role whose policies show only what an open grant covers, each read audited under the client (`policy-access-control.md` §2.1) |

Note: operator actions on a client tenant are audited **under that client's tenant** (findings A15). Those rows form part of the client's audit trail and are covered by Part 2 as well; we rely on them as controller only for our own accountability.

### C5. Usage and cost ledger; aggregated service metrics

| Field | Entry |
| --- | --- |
| Purpose | Billing, the per-tenant external-model spend cap, capacity planning |
| Legal basis | Contract with the client (Art. 6(1)(b) is not available because the client, not the user, is the contracting party); legitimate interests, Art. 6(1)(f), as far as personal data is involved at all |
| Data subjects | None directly (see reasoning) |
| Categories | `usage_ledger`: tenant, month, model, tokens in, tokens out, cost. No user, no question text |
| Recipients | Our operators; the client sees its own figures (operator console from P1b-12) |
| Transfers | None |
| Retention | [confirm: proposed 7 years for invoicing records, or the statutory accounting period] |
| TOMs | Tenant-scoped table with RLS; cross-tenant aggregates show no query text |

**Reasoning on the role, for the owner to confirm.** The ledger counts tokens per tenant per month per model. It names no user, so it is not personal data about the client's users; it is data about the client as a business. We record it here as our own record for billing. If a client is a sole trader, or a tenant has a single user, the figures could relate to an identifiable person; in that case they remain our billing record (controller) and are kept to the accounting period. Aggregated, pseudonymised cross-tenant metrics with a minimum group size are the only use of query data across tenants (compliance addendum Oct 17), and no such pipeline is built today.

### C6. Requests sent to us: takedowns, data-subject requests about the corpus, privacy and security contacts

| Field | Entry |
| --- | --- |
| Purpose | Handling publisher takedowns, objections and erasure requests from people named in sources, and security reports |
| Legal basis | Legal obligation, Art. 6(1)(c) (Art. 12 to 22 GDPR); legitimate interests for takedowns and security reports |
| Data subjects | Requesters (publishers' staff, people named in sources, researchers) |
| Categories | Name, email, the request, our decision and its date |
| Recipients | Our operators; counsel where needed |
| Transfers | None intended; the mailbox provider for privacyanddata@myceliumgastronomy.com is [confirm provider and location] |
| Retention | 3 years after the request is closed [confirm], to evidence handling |
| TOMs | Request log kept in [document store]; takedown queue in the content console from Phase 1b (P1b-03) |

### C7. Business contacts of clients and prospects

| Field | Entry |
| --- | --- |
| Purpose | Contracting, invoicing, account management, onboarding and offboarding |
| Legal basis | Legitimate interests (B2B relationship); legal obligation for invoices |
| Data subjects | Client signatories, IT and privacy contacts, billing contacts |
| Categories | Name, job title, business email and phone |
| Recipients | Our staff; accountant [confirm] |
| Transfers | [confirm mailbox and accounting tools and their locations] |
| Retention | Term of the contract plus [confirm: limitation period]; invoices for the statutory period |
| TOMs | `policy-access-control.md` |

### C8. Security and abuse monitoring

| Field | Entry |
| --- | --- |
| Purpose | Detecting misuse: sign-in link abuse, download caps, external spend thresholds |
| Legal basis | Legitimate interests, Art. 6(1)(f) |
| Data subjects | Clients' users |
| Categories | Counters and refusals: link requests per user (`auth.link_refused`), downloads per user per day (`download.refused`), spend notices |
| Recipients | Our operators |
| Retention | Audit events 12 months; sign-in link rows expire after 15 minutes and are purged from Phase 1b (P1b-14) |
| TOMs | Built: per-user sign-in link limit, 50 downloads per user per day. Not built: per-user and per-tenant query rate limits, bulk-extraction detection, alerting |

Note: the audit rows used here are part of the client's audit trail (Part 2). We use them for the security of the service under the DPA clause 1.4 position (controller for our own security monitoring).

### C9. Client declarations for supplied documents

*DRAFT addition, Oct 22, 2026 (P1b-19 step 1; architecture §15).*

| Field | Entry |
| --- | --- |
| Purpose | Evidencing the client's declaration of rights and downloadability for documents it supplies (terms §6A) |
| Legal basis | Legitimate interests (contract evidence, defence of claims), Art. 6(1)(f); contract with the client |
| Data subjects | The client's signatory |
| Categories | Name, title, signature, date; file names and declarations |
| Recipients | Our operators; counsel where needed |
| Transfers | None |
| Storage | [document store]; reference in the source register (`client_declaration_ref`) |
| Retention | Term of the contract plus [limitation period] |
| TOMs | `policy-access-control.md` |

---

## Part 2 — Processor register (Art. 30(2))

One sheet per client. The first is [Client].

### P-[Client]. Research assistant service for [Client]

| Field | Entry |
| --- | --- |
| Controller | [Client legal name], [Client address]; privacy contact [ ] |
| Processor | Estefania Simon-Sasyk y Otro CB; privacyanddata@myceliumgastronomy.com |
| Contract | Client DPA (`client-dpa-draft.md`), dated [date]; part of the agreement in `terms-of-service.md` |
| Categories of processing | (1) Authenticating users with emailed sign-in links (SSO from Phase 1b, P1b-07); (2) storing questions, answers, citations and feedback for the retention period; (3) sending prompts to language models to answer; (4) serving the workspace file list and licence-gated downloads; (5) recording the audit trail of [Client]'s users and administrators; (6) applying administrators' settings (users, retention, workspace defaults, additional instructions); (7) time-boxed support access (P2A-08): on a grant by one of [Client]'s administrators, for 15 minutes to 4 hours, our operator reads the granted settings or one of that administrator's own conversations, read only; each grant and read is an audit event shown to [Client]'s administrators |
| Data subjects | [Client]'s employees and contractors invited as users; [Client]'s administrators |
| Categories of personal data | Account data (email, name if given, role, status, last sign-in time and method); content (questions, conversation turns, answers, citations, feedback comments, model and reasoning choice, any personal data typed into a question); workspace additional instructions; downloads (user, file, time); audit metadata (user UUID, event, time, workspace, model; no text); technical (session tokens, IP address at sign-in) |
| Special categories | None intended; users are instructed not to enter them (`terms-of-service.md`, acceptable use) |
| Sub-processors | `sub-processors.md`: Scaleway SAS (hosting and Transactional Email in Paris; Generative APIs in the European Union). Mailgun EU listed as optional backup, not active. OpenRouter, AWS Bedrock, Microsoft Azure only if external models are enabled |
| Transfers outside the EEA | None by default. Only in the external-models mode, which is **off for [Client]** today; when enabled, under the SCCs ([SCC module]) in OpenRouter's DPA and `transfer-impact-assessment.md`, after [Client]'s signed acceptance (DPA Annex 4) and the checklist in `paperwork-checklist.md` |
| Retention | Conversations at most 30 days, settable 1 to 30 by [Client]'s administrators; Phase 1a hides expired conversations at read time and the purge job deletes them from Phase 1b (P1b-14), which also brings a 0-day "no history" setting. Accounts for the term. Audit 12 months; no disposal path yet (open question C1, backlog "Enterprise requirements"). Download records 90 days from Phase 1b (P1b-14). Support grants (scope, duration, note; no user identifier) for the term, closed by the daily purge when expired. On termination, deletion within [30] days with a certificate (P1b-14, `offboarding-pack.md`), support grants included |
| TOMs | `client-dpa-draft.md` Annex 2, with the "not yet built" list in its owner note 7; `policy-information-security.md` |
| Date started | [date] (first user of [Client] invited Oct 21, 2026: the administrator account) |

### Template for further clients

Copy the sheet above, replace [Client], and record: whether the client supplies documents (DPA clause 7A; DRAFT addition, Oct 22, 2026 (P1b-19 step 1; architecture §15).); if so, add to "Categories of processing" "(7) parsing, indexing and searching documents [Client] supplies, showing excerpts to its users, sending excerpts to language models, and serving downloads where declared", to "Categories of personal data" "personal data in client-supplied documents as declared", to "Retention" "client-supplied documents until withdrawn, deleted at termination with the certificate", and to "Data subjects" "people named in client-supplied documents"; the date of the DPA, whether external models are enabled (acceptance reference and date), whether any answer mode beyond corpus-only is enabled, the retention set by the client, and the SSO source kind (P1b-07).

---

## Change log

| Date | Change |
| --- | --- |
| Oct 21, 2026 | First draft (P1b-09) |
| Oct 22, 2026 | DRAFT: client-supplied documents (P1b-19 step 1) |
| Oct 25, 2026 | DRAFT: time-boxed support access (P2A-08, P2A-10) in C4 and the Part 2 sheet |
