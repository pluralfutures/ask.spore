# Security Questionnaire (Pre-filled, CAIQ-lite Shape) — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Revision | Oct 22, 2026, **DRAFT**: client-supplied documents (P1b-19 step 1, architecture §15): scope line and rows 4.2, 4.3, 14.1, 14.5, 15.1, 16.3 and new section 17. Use section 17 only for a client that supplies documents, and only once P1b-19 step 2 is built; until then answer "No" to 17.1. Placeholders added: [secure transfer method], [5] (working days) |
| Placeholders | [Client], [security contact email], [privacy contact email], [support email], [number of staff], [DPO or privacy contact name], [insurance cover], [address], [name], [30] and [48] (DPA notice periods), [date] |
| To finalise, the owner must | (1) fill in the placeholders; (2) re-check every "Partial" and "No" row against the build on the day the questionnaire is sent, and update the ones that Phase 1b items have closed (each names its spec item); (3) confirm row 6.3 (encryption at rest of the Instance volumes) with Scaleway and replace "[confirm]"; (4) answer the HR rows (section 3) yourself; they are about the company, not the system; (5) keep this file as the master and copy answers into a client's own questionnaire format, never the other way round; (6) have counsel check the privacy rows (section 14) against the signed DPA. |

How to read the answers: **Yes** means built and verified, with the evidence named. **Partial** means part of the control is in place; the detail says which part. **No** means not in place; where it is planned, the spec item is named. **N/A** means it does not apply to this service. Status is as of Oct 21, 2026, after the Phase 1a release (findings §10 to §12).

Scope: SporeBot, a multi-tenant research assistant answering questions from a curated corpus of public sources and our own analysis, with citations. Clients upload no documents (a client that supplies documents under the terms §6A: see section 17). The data we hold for a client is its users' accounts, their questions and conversations (at most 30 days), downloads records and audit metadata.

---

## 1. Company and certifications

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 1.1 | Legal entity and address | — | Estefania Simon-Sasyk y Otro CB, [address] |
| 1.2 | Number of staff with access to production | — | [number of staff]. Today one person (the owner) holds the operator and content roles |
| 1.3 | SOC 2 report available? | No | Target: SOC 2 Type II, Security and Confidentiality criteria. Observation window not yet started. Until then we provide this questionnaire, the DPA annexes and the policy set |
| 1.4 | ISO 27001 certified? | No | Not pursued (decision Oct 17, 2026) |
| 1.5 | Penetration test in the last 12 months? | No | Not yet scheduled. Planned before the SOC 2 observation window |
| 1.6 | Cyber insurance | — | [insurance cover] |

## 2. Governance and policies

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 2.1 | Documented information security policy? | Partial | Drafted, awaiting owner approval: `policy-information-security.md` and the policy set (access control, change management, incident response, vendor management, data retention and disposal, business continuity) |
| 2.2 | Named security owner | Yes | The owner, [name], acts as security lead |
| 2.3 | Risk assessment performed and documented? | Partial | Risk register drafted (`risk-register.md`); annual review once approved |
| 2.4 | Policies reviewed at least annually? | No | First approval pending; annual review written into each policy |
| 2.5 | Acceptable use rules for customers | Partial | In `terms-of-service.md` (draft): no bulk extraction or redistribution of corpus content, suspension rights |

## 3. Human resources

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 3.1 | Background checks for staff with production access, where lawful | [owner] | |
| 3.2 | Confidentiality agreements signed by staff and contractors | [owner] | |
| 3.3 | Security awareness training, annual | [owner] | |
| 3.4 | Access removed within 24 hours of departure | Partial | Procedure in `policy-access-control.md` and `offboarding-pack.md` §4; not yet exercised (one person holds production access) |

## 4. Asset management

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 4.1 | Inventory of systems holding customer data | Yes | One Scaleway Instance in Paris (fr-par) running the API, web app, PostgreSQL, Redis, Authentik, Caddy and RAGFlow in Docker Compose; listed in `sub-processors.md` and `records-of-processing.md` |
| 4.2 | Data classification | Yes | Data map in the compliance design guide: questions and conversations are the confidential asset; corpus is public or licensed content. Documents a client supplies are classified as confidential customer data like conversations (DRAFT, Oct 22, 2026) |
| 4.3 | Inventory of third-party content and licences | Partial | Source register with licence basis per source; approval workflow and licence-file attachment from Phase 1b (P1b-01, P1b-05). Client-supplied files are recorded with the basis `client-supplied`, the supplying client and the client's declaration (section 17) (DRAFT, Oct 22, 2026: client-supplied documents are a design, P1b-19, not built) |

## 5. Access control and identity

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 5.1 | SSO with the customer's identity provider (SAML/OIDC)? | No — planned Phase 1b (P1b-07) | Order: Microsoft Entra ID, Google Workspace, generic OIDC and SAML. Today users sign in with single-use emailed links (5.2) |
| 5.2 | Password-less or password policy | Yes | No passwords. Emailed single-use links: 15-minute expiry, consumed only by a button press (POST) on the landing page so mail scanners cannot use them, bound to the requesting browser, at most 5 per user per link lifetime, no account enumeration |
| 5.3 | MFA for customer administrators | No — planned Phase 1b (P1b-08) | Enforced through an Authentik authenticator validation stage bound to the admin group |
| 5.4 | MFA for provider staff | Partial | Operator sign-in goes through Authentik; hardware-key MFA for operators is Authentik configuration and not checked by the API (findings A12). [owner: confirm configured] |
| 5.5 | Role-based access | Yes | Tenant roles: user and tenant administrator. Provider roles: operator (separate internal tenant) and, from Phase 1b, content editor and reviewer (P1b-01). Tested |
| 5.6 | Can provider staff read customer conversations? | No | The operator database role has no privilege on conversations, messages, citations, feedback or sign-in links (revision 0006, tested). Support access to a specific conversation only at the customer's request; time-boxed, logged support mode is not yet built |
| 5.7 | Customer can deactivate its users | Yes | Tenant administrator deactivates a user; the next request is refused; audited (`tenant_admin.user_changed`) |
| 5.8 | Quarterly access reviews | No | Written into `policy-access-control.md`; first review after approval |
| 5.9 | Session timeout | Partial | Session valid 8 hours; the session cookie is cleared on sign-out and the token's revocation is verified live in Phase 1b (P1b-08); refresh before expiry from Phase 1b (P1b-08) |
| 5.10 | Customer can see sign-in and admin events for its users | Partial | Every sign-in, sign-out and admin action is written to the audit log. A download of the audit log for tenant administrators is not built; until it is, we provide an export on request |

## 6. Cryptography

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 6.1 | Encryption in transit | Yes | TLS at Caddy with automatic certificates; HTTP redirects to HTTPS; security headers present (findings §10, step 3). All calls to model and email providers over HTTPS (startup check) |
| 6.2 | TLS version | Yes | TLS 1.2 and above |
| 6.3 | Encryption at rest | Partial | [confirm] whether the Instance's Block Storage volumes are encrypted at rest by Scaleway. Backups are encrypted (owner-run, see 13.2) |
| 6.4 | Key and secret management | Partial | Secrets are environment files on the Instance, outside the repository and git-ignored. Scaleway Secret Manager is in the backlog. Rotation on staff departure per `policy-access-control.md` |
| 6.5 | Per-customer encryption keys | No | Not offered. Customer data is separated by row-level security, not by key |

## 7. Physical security

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 7.1 | Data centre physical controls | N/A (inherited) | Scaleway data centres in the Paris region. We rely on Scaleway's certifications; reports kept per `policy-vendor-management.md` |
| 7.2 | Provider offices hold customer data? | No | No customer data on staff devices; never debug with real queries (repository rule) |

## 8. Operations and logging

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 8.1 | Application logs exclude customer content | Yes | Logs go through one allow-listed logging function; questions, answers, prompts, passages, headers and tokens are never logged; a static check over the code and tests prove it. Unhandled errors are reduced to one allow-listed line (fix e0435c1, findings §12). Access logs off at the API and at Caddy |
| 8.2 | Audit log of security events | Yes | Append-only audit table: sign-ins (with method), sign-outs, admin and operator actions, queries (metadata only, no question or answer text), downloads, feedback. A database trigger rejects UPDATE and DELETE for every role |
| 8.3 | Audit log retained 12 months, write-once | Partial | Append-only in the database. The daily export to write-once object storage is not built (backlog) |
| 8.4 | Central monitoring and alerting | No | Monitoring stack is in the backlog (owner decision Oct 21, 2026). Operator notices exist for external-model spend (80 and 100 percent) and for workspace texts matching tenant names |
| 8.5 | Vulnerability scanning | No | Not scheduled |
| 8.6 | Patch management | Partial | Pinned image tags for RAGFlow, Authentik, PostgreSQL, Redis, Caddy; digest pinning from Phase 1b (P1b-15). OS updates [owner: confirm automatic security updates] |
| 8.7 | Capacity and rate limiting | Partial | Download cap of 50 per user per day; sign-in link cap per user; external-model spend cap per customer. Per-user and per-customer query rate limits and bulk-extraction detection are not built |

## 9. Network security

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 9.1 | Only required ports exposed | Yes | Public listener is Caddy on 80 (redirect) and 443 only; database, RAGFlow API and object store ports closed, checked from outside on Oct 21, 2026 (findings §10) |
| 9.2 | Internal services isolated | Yes | RAGFlow has no public listener; its UI is bound to loopback; no API route proxies it |
| 9.3 | Outbound connections restricted | Yes | Every outbound host is in an allow-list in configuration, split into EU and external hosts; the API refuses to start otherwise, and refuses an external host for a customer without the entitlement (tested) |
| 9.4 | DDoS protection | Partial | Scaleway network-level protection [confirm]; no dedicated WAF |

## 10. Application security and SDLC

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 10.1 | Tenant isolation | Yes | Row-level security, forced, on all 18 customer tables, set per request from the authenticated user; tenant-first indexes; tenant-prefixed cache keys. Tests prove a cross-tenant read returns nothing; independent review signed Oct 21, 2026 (findings §12) |
| 10.2 | Customer cannot choose which corpus is searched | Yes | Datasets are resolved on the server from the workspace; any request body carrying dataset or document IDs is refused (tested) |
| 10.3 | Code review and CI | Yes | Changes by pull request; CI runs lint, strict type checks, unit and database tests, evaluation and guardrail checks |
| 10.4 | Branch protection enforcing CI | No — planned Phase 1b (P1b-13(c)) | Six merges were made on red CI in the Phase 1a release (findings §10, F9); branch protection is the fix |
| 10.5 | Separate test environment with no customer data | Partial | Tests use synthetic fixtures only (repository rule). Staging host not yet set up; one production Instance |
| 10.6 | Secure coding rules | Yes | Repository rules enforced by tests and static checks: no bodies in logs, no client-supplied dataset IDs, no identifiers to the model, no direct cache access |
| 10.7 | Dependency pinning | Partial | Python and JavaScript dependencies pinned; container images pinned by tag, by digest from Phase 1b (P1b-15) |

## 11. Vendor management

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 11.1 | List of sub-processors | Yes | `sub-processors.md`: Scaleway (hosting, inference, email); Mailgun EU (backup email, not active); OpenRouter, AWS Bedrock, Microsoft Azure only for the optional external-models mode, off for every customer |
| 11.2 | DPAs with sub-processors | Partial | Scaleway DPA [owner: reference]; OpenRouter DPA with SCCs to be filed before external models are ever enabled (`paperwork-checklist.md`) |
| 11.3 | Notice of sub-processor changes | Yes (contractual) | [30] days' notice with a right to object (DPA clause 5.2, draft) |
| 11.4 | Vendor security reviews | Partial | Process in `policy-vendor-management.md` (draft) |

## 12. Incident response

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 12.1 | Documented incident response plan | Partial | `policy-incident-response.md` and `incident-runbook.md` (drafts) |
| 12.2 | Breach notification to customers | Yes (contractual) | Without undue delay and within [48] hours of becoming aware (DPA clause 9.1, draft) |
| 12.3 | Incident tabletop exercise in the last year | No | First tabletop planned before the SOC 2 observation window |
| 12.4 | Security contact | Yes | [security contact email] |

## 13. Business continuity and disaster recovery

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 13.1 | Documented BCP/DR plan | Partial | `policy-business-continuity.md` (draft) |
| 13.2 | Backups, encrypted, off-host | Partial | Nightly encrypted backup of the database and RAGFlow volumes to Scaleway Object Storage in Paris with object lock and 30-day retention, run by the owner outside the build spec; restore test pending (to be recorded in the Phase 1b findings) |
| 13.3 | High availability | No | One Instance. A second host is in the backlog. A model-provider failure falls back to another Paris-hosted model |
| 13.4 | RTO / RPO | — | [owner: set targets in `policy-business-continuity.md`] |

## 14. Privacy and GDPR

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 14.1 | Your role under GDPR | — | Processor for the customer's user data (accounts, sign-in events, conversations, downloads) and for any documents the customer supplies (section 17). Controller for the public-source corpus and our own operational logs (owner decision Oct 20, 2026) |
| 14.2 | DPA offered | Yes | `client-dpa-draft.md` (draft for counsel) |
| 14.3 | Customer data used to train models? | No | Never, by us or by model providers (zero-retention terms; data collection denied on external requests) |
| 14.4 | Retention of conversations | Yes | At most 30 days; the customer may shorten it to 1 to 30 days; no setting allows more (database constraint, tested). Expired conversations disappear from the service at once; deletion from the database by the purge job from Phase 1b (P1b-14), which also adds a 0-day "no history" setting |
| 14.5 | Deletion at termination with certificate | Partial | Procedure in `offboarding-pack.md`, including client-supplied documents (section 17); the automated per-customer purge and the certificate figures from Phase 1b (P1b-14); until then a manual procedure |
| 14.6 | Data export | Partial | No self-service export of conversations. On request, an operator export of accounts and current conversations |
| 14.7 | Data subject request handling | Yes (process) | Forwarded to the customer as controller; we assist within [30] days (DPA clause 8) |
| 14.8 | DPIA performed | Partial | `dpia.md` (draft) |
| 14.9 | Privacy notice | Partial | `privacy-notice.md` (draft); shown and accepted at first sign-in from Phase 1b (P1b-10) |
| 14.10 | DPO or privacy contact | — | [DPO or privacy contact name], [privacy contact email] |

## 15. Data residency and transfers

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 15.1 | Where is customer data stored? | Yes | Paris, France (Scaleway fr-par): application, database, index, files (including any documents the customer supplies), logs, backups |
| 15.2 | Where is it processed by AI models? | Yes | By default Scaleway Generative APIs in Paris (DeepSeek V4.1 Flash, Qwen 3.8 27B) |
| 15.3 | Any transfer outside the EEA? | No by default | Only if the customer opts in to external models (DPA clause 6 and Annex 4): prompts go through OpenRouter's EU endpoint to AWS Bedrock (Claude) or Microsoft Azure (GPT), which may process outside the EEA. Off for every customer today; SCCs and a transfer impact assessment (`transfer-impact-assessment.md`) are required first |
| 15.4 | Email provider location | Yes | Scaleway Transactional Email, Paris; receives the recipient address and the email only |

## 16. AI-specific questions

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 16.1 | Is our data used to train or fine-tune any model? | No | We do not train or fine-tune. Providers are bound by zero-retention terms |
| 16.2 | Zero data retention at the model provider | Partial | Scaleway states no retention for Generative APIs; the written confirmation naming our organisation, models and endpoint is pending (findings M2). For external models, ZDR routing and data collection denied are set on every request and asserted by tests |
| 16.3 | What is sent to the model? | Yes | The platform instructions, the workspace's additional instructions, retrieved source passages with publisher, title, date and page (for a customer that supplies documents, including passages from them, never another customer's), recent conversation turns and the question. No user, account, organisation or workspace identifiers (tested on every build) (DRAFT, Oct 22, 2026: client-supplied documents are a design, P1b-19, not built) |
| 16.4 | Can the model act (tools, browsing, writes)? | No | The model has no tools. Retrieval is read-only. Public-source text is marked as untrusted in the prompt |
| 16.5 | Prompt-injection testing | Yes | A guardrail evaluation with adversarial workspace instructions and passages runs in CI (mocked) and was run live at release; every block passes except "drop citations", which is enforced in code instead: an uncited corpus-only answer is never shown (findings §11, G6) |
| 16.6 | Hallucination controls | Yes | Answers cite their sources; corpus-only mode withholds uncited answers and declines when sources do not answer; an evaluation set measures citation precision, faithfulness and abstention and gates prompt changes (findings §11, G9). Answers are labelled "AI-generated, verify against cited sources" |
| 16.7 | General-knowledge mode | Yes | Optional, enabled per customer by our operator; uncited sentences are marked and the answer carries a mode banner |
| 16.8 | Model versions pinned | Yes | Model names pinned in configuration; aliases such as "latest" refused at startup |
| 16.9 | EU AI Act position | Yes | Limited-risk system with transparency duties; see `ai-act-technical-documentation.md` and `ai-transparency-note.md` (drafts) |
| 16.10 | Can one customer's questions influence another's answers? | No | Answer caches are keyed per customer; conversations isolated by row-level security; usage across customers only as aggregated metrics with a minimum group size |

## 17. Customer-supplied documents

*DRAFT addition, Oct 22, 2026 (P1b-19 step 1; architecture §15). Designed, not built: answers describe the design and become "Yes" only once P1b-19 step 2 passes its tests. For the test client: 17.1 "No", omit the rest.*

| # | Question | Answer | Detail and evidence |
| --- | --- | --- | --- |
| 17.1 | Can we upload or supply our own documents? | [Planned / Yes] | By arrangement: you send files (PDF, DOCX, PPTX) with a declaration per file or batch by [secure transfer method]; our content team registers them. No self-service upload |
| 17.2 | Who can see our documents? | Your users only | Each file is recorded with your organisation as its supplier and placed only in content collections owned by your organisation; the application, the ingestion worker and the database each refuse to place it in a collection of another customer or a shared one. Identical files from two customers are kept separately. Tests prove another customer's workspace never retrieves, lists or downloads it |
| 17.3 | Are our documents used to train models or for other customers? | No | Used only to answer your users' questions. Model providers receive excerpts in prompts under zero-retention terms |
| 17.4 | Where are our documents processed? | Paris | Stored, parsed and indexed on our Scaleway Instance in Paris; the parser runs on an internal network with no public access. Excerpts go to the EU model provider, and outside the EU only if you have accepted external models (DPA clause 6) |
| 17.5 | Can our users download our documents? | As you declare | Only your users, only files your declaration marks downloadable; single-use links, daily cap, audited |
| 17.6 | Can we withdraw a document? | Yes | On written request within [5] working days: file, text and index entries deleted; passages cited in past answers marked withdrawn |
| 17.7 | What happens at termination? | Deleted | Every supplied document, its text, index and stored copy is deleted and listed in the certificate of deletion; on request before the end we return the copies we hold |
| 17.8 | Who is responsible for rights in the documents and for people named in them? | You | You warrant your rights and indemnify us for third-party claims (terms §6A); you are controller for personal data in them and we are your processor (DPA clause 7A) |
| 17.9 | Are document contents treated as instructions to the model? | No | Document text is passed as untrusted data; the model has no tools, so text in a document cannot make it act |
| 17.10 | Is our content malware-scanned? | [owner] | Files are accepted only in the listed formats and parsed on an isolated internal network. [Whether a malware scan is added: open-questions J] |
