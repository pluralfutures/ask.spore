# Data Processing Agreement — Draft for the Test Client

| | |
| --- | --- |
| Status | **DRAFT — not for signature. The owner's counsel must review this agreement before it is sent to [Client] or signed.** |
| Date | Oct 19, 2026 |
| Author | Drafted for owner review (spec item P1a-15) |
| Revision | Oct 22, 2026, **DRAFT**: clause 7A (client-supplied documents) and the matching changes to clauses 1.3, 6.3, 10.5 and Annexes 1 to 3, for clients that supply their own documents (P1b-19 step 1, architecture §15). For the test client, which supplies nothing, delete clause 7A and keep clause 1.3 option (a). Withdrawal window, limits and channel filled in by the owner, Oct 22, 2026 |
| Roles position | **Pending the owner's confirmation**: we act as processor for [Client]'s user data (accounts, questions, conversations, downloads, audit of [Client]'s users) and as controller for the public corpus, our own platform logs and security monitoring. This differs from the compliance guide's data map, which treats account data and audit logs as ours as controller; see "Notes for the owner" at the end. |
| To finalise, the owner must | (1) confirm or change the roles position; (2) fill in every square-bracket placeholder; (3) decide the open points in "Notes for the owner"; (4) have counsel review; (5) attach the final sub-processor list and TOMs; (6) record the signed acceptance reference (document and date) in the operator console before enabling external models (findings A13). |

---

This Data Processing Agreement ("**DPA**") forms part of the [Services Agreement / Order Form] dated [date] (the "**Agreement**") between:

- **[Client legal name]**, [legal form], registered at [address], company number [ ] ("**[Client]**" or the "**Controller**"); and
- **Estefania Simon-Sasyk y Otro CB**, a comunidad de bienes under Spanish law trading as Mycelium Gastronomy Network, NIF E19824093, registered at [address] ("**Provider**" or the "**Processor**").

## 1. Definitions and scope

1.1 Terms used in this DPA ("personal data", "processing", "controller", "processor", "data subject", "personal data breach", "supervisory authority") have the meaning given in Regulation (EU) 2016/679 ("**GDPR**").

1.2 This DPA applies to personal data that the Processor processes on behalf of [Client] in providing the research assistant service (the "**Service**"), as described in Annex 1 ("**Client Personal Data**").

1.3 *Owner: choose one.* (a) **No client content.** [Client] does not upload documents to the Service. The research corpus consists of published third-party sources and the Provider's own analysis. The Provider is the controller of the corpus and of any personal data in it, and this DPA does not cover it. (b) *DRAFT addition, Oct 22, 2026 (P1b-19 step 1, client-supplied documents; architecture §15).* **Client-supplied documents.** [Client] supplies documents for its workspaces under clause 7A; they and any personal data in them are Client Personal Data covered by this DPA. The Provider may supplement [Client]'s workspaces with published third-party sources and its own analysis; the Provider is the controller of that content and of any personal data in it, and this DPA does not cover it.

1.4 The Provider is also controller, outside this DPA, for its own platform operation and security logs, security monitoring and aggregated, pseudonymised service metrics, processed for the security and integrity of the Service under its own legitimate interests. The Provider describes this processing in its privacy notice.

## 2. Processing on instructions

2.1 The Processor processes Client Personal Data only on [Client]'s documented instructions, which are this DPA, the Agreement and the settings [Client]'s administrators make in the Service, unless required to do otherwise by Union or Member State law, in which case it informs [Client] before processing unless that law prohibits it.

2.2 The Processor informs [Client] immediately if, in its opinion, an instruction infringes the GDPR.

2.3 The Processor does not use Client Personal Data to train or fine-tune any model, does not sell it, and does not use it for any purpose other than providing the Service. Questions and conversations are used for service improvement only as aggregated, pseudonymised metrics with a minimum group size, never as text.

## 3. Confidentiality of questions

3.1 Questions, answers and conversations of [Client]'s users are never visible to, shared with, or used to answer the questions of, any other customer of the Provider. They are isolated per customer by database row-level security and per-customer cache keys.

3.2 Persons authorised to process Client Personal Data are bound by confidentiality. Provider staff do not read conversation content except where [Client] asks for support on a specific conversation, or as required by law; any such access is time-boxed and logged.

## 4. Security

4.1 The Processor implements the technical and organisational measures in Annex 2 and keeps them at least at that level for the term of this DPA.

## 5. Sub-processors

5.1 [Client] gives general authorisation to the sub-processors listed in Annex 3.

5.2 The Processor gives [Client] at least **[30] days'** written notice of an intended addition or replacement of a sub-processor. [Client] may object on reasonable data-protection grounds within that period; the parties then discuss in good faith, and if they cannot agree, [Client] may terminate the affected part of the Service without penalty.

5.3 The Processor imposes on each sub-processor data protection obligations no less protective than this DPA, and remains liable to [Client] for its sub-processors' performance.

## 6. Optional mode: external models

6.1 By default the Service sends prompts only to language models hosted in the European Union (Annex 3, Scaleway Generative APIs, Paris).

6.2 [Client] may opt in to **external models** (at the date of this DPA: Claude Opus 5.5 and GPT-6.1 Sol). When enabled, a user who chooses an external model for a conversation causes that conversation's prompts to be sent to **OpenRouter, Inc.** through its EU endpoint, which forwards them to the upstream vendor pinned for that model (Amazon Web Services Bedrock for Claude; Microsoft Azure for GPT). These vendors may process the prompt outside the European Economic Area. The region of processing is **[EU (Ireland for AWS; [country] for Azure) / the United States], per the Provider's transfer impact assessment dated [date]** (*owner: fill in after the verification in the TIA §10; until verified, state "may be outside the EEA, including the United States"*).

6.3 What is sent: the platform's instructions, [Client]'s workspace additional instructions, excerpts of public sources and, where clause 7A applies, excerpts of documents [Client] supplied, recent conversation turns and the user's question. No user, account or customer identifier is sent.

6.4 Transfer mechanism: the EU Standard Contractual Clauses (Decision (EU) 2021/914), module [3] [and 2], in OpenRouter's data processing agreement, with the supplementary measures in the Provider's transfer impact assessment (zero-data-retention routing, provider data collection denied, EU endpoint, provider pins, no identifiers in prompts).

6.5 Each model provider in Annex 3 processes prompts under zero-data-retention terms, subject to the exception common to such terms: a provider may retain a request where required by law or to investigate misuse of its service.

6.6 External models are enabled only by the Provider's operator, only after [Client] signs the acceptance in Annex 4, and only up to the monthly spend cap agreed in Annex 4. Users see on the model picker that these models are served outside the EU. [Client] may withdraw the opt-in at any time by written notice; the Provider then disables external models within [2] working days.

## 7. Downloads of corpus files

7.1 Users may see the list of files in each workspace's corpus and may download a file only where the Provider has marked that source as downloadable on the basis of its licence (at the date of this DPA, in practice the Provider's own analyses). Other files are shown with a link to the publisher.

7.2 Each download is processed as Client Personal Data: the Service records which user downloaded which file and when, issues a single-use link valid for 60 seconds, and limits downloads per user per day ([50]). These records are part of the audit log (Annex 1).

## 7A. Client-supplied documents

*DRAFT addition, Oct 22, 2026 (P1b-19 step 1, client-supplied documents; architecture §15).* *Only for a client that supplies documents; delete for the test client.*

7A.1 [Client] may send the Processor documents (PDF, DOCX or PPTX, up to 500 MB each, 100 per batch; larger files only after consultation, terms §6A.1) for its workspaces by email, by a link to a file share [Client] controls, or by another agreed channel, each file or batch with a written declaration naming the files, stating whether its users may download each one, and stating whether it contains personal data of people other than [Client]'s staff. [Client] does not supply special-category data or data about criminal offences unless agreed in writing beforehand.

7A.2 The Processor processes client-supplied documents only to provide the Service to [Client]: it parses and indexes them, shows excerpts with citations to [Client]'s users, sends excerpts in prompts to the language models in Annex 3 (external models only under clause 6) and, where the declaration allows, lets [Client]'s users download them. Unless the Agreement excludes it, it also tests the quality of answers on them in [Client]'s own workspaces and keeps only the resulting scores (terms §6A.5). It does not use them for any other customer, to train any model, or for its own purposes.

7A.3 Client-supplied documents are searched only from [Client]'s own workspaces. The Processor keeps them in collections that belong to [Client] and never places them in a collection available to another customer (Annex 2).

7A.4 [Client] is the controller of personal data in the documents it supplies and is responsible for having a lawful basis to supply them and for informing the people named in them (Article 14 GDPR). The Processor forwards to [Client] any request or claim it receives about a client-supplied document (clause 8.1).

7A.5 On [Client]'s written request, the Processor withdraws a client-supplied document from the Service within 10 working days: the file, its text, its index entries and any copy the Processor holds outside the Service are deleted, and passages already cited in conversations are marked as withdrawn. Where the Processor receives a third party's notice that a document infringes its rights, it may withdraw the document at once and tells [Client] without undue delay (terms §6A.6). Excerpts already cited in [Client]'s conversations stay, marked as withdrawn, when [Client] withdraws a document itself; they are blanked when the withdrawal follows a third party's rights claim.

7A.6 [Client]'s warranty of rights and indemnity for client-supplied documents are in the Agreement (terms §6A), not in this DPA.

## 8. Data subject requests and assistance

8.1 The Processor assists [Client], taking into account the nature of the processing, in responding to data subject requests (Articles 12 to 22 GDPR). It forwards any request it receives directly to [Client] without undue delay and does not respond itself except on instruction.

8.2 [Client]'s administrators can deactivate users and shorten retention themselves. For export or erasure of a specific user's data, [Client] contacts [privacy contact]; the Processor completes the request within [30] days.

8.3 The Processor assists [Client] with data protection impact assessments and prior consultations (Articles 35 and 36) to the extent they concern the Service.

## 9. Personal data breach

9.1 The Processor notifies [Client] without undue delay, and in any event within **[48] hours**, after becoming aware of a personal data breach affecting Client Personal Data, with the information Article 33(3) GDPR requires as far as available, and updates it as more becomes known.

9.2 The Processor takes reasonable steps to contain and remedy the breach and documents it.

## 10. Retention and deletion

10.1 **Chat history** (questions, answers, citations, feedback) is retained for **at most 30 days** from the start of the conversation. [Client]'s administrators may shorten this to between 1 and 30 days; no setting allows more than 30 days.

10.2 *Owner: choose one before signature.* (a) "Conversations older than the retention period are no longer accessible in the Service and are deleted from the Provider's systems within [7] days, and from backups within [35] days." — true only once the purge job (Phase 1b) runs. (b) "Conversations older than the retention period are no longer accessible in the Service; they are permanently deleted by [date]." — matches the Phase 1a build, where expiry applies at read time and the purge job is not yet built.

10.3 **Accounts** are retained for the term of the Agreement. Deactivated users remain as records so that audit history stays complete; [Client] may ask for their deletion under clause 8.

10.4 **Audit records** of [Client]'s users (sign-ins, administrative actions, query and download metadata; never question or answer text) are retained for **12 months** in write-once storage.

10.5 On termination the Processor deletes all Client Personal Data within [30] days, including every client-supplied document with its parsed text, index entries and stored copy (clause 7A; *DRAFT addition, Oct 22, 2026*), except audit records kept for the remainder of their 12-month retention where needed to evidence security and compliance, and confirms deletion in writing on request. Given the retention above, no export is normally needed; on request before termination the Processor provides an export of accounts and current conversations in a common machine-readable format.

## 11. Audits

11.1 The Processor makes available the information necessary to demonstrate compliance with Article 28 GDPR. Once available, its SOC 2 Type II report (Security and Confidentiality) satisfies [Client]'s audit right; until then, completed security questionnaires and this DPA's annexes. Where these are insufficient, or a supervisory authority requires it, [Client] may conduct an audit on [30] days' notice, at its cost, no more than once a year, under confidentiality.

## 12. International transfers

12.1 Apart from the optional mode in clause 6, Client Personal Data is processed and stored only in the European Union (Scaleway, Paris). The Processor does not transfer Client Personal Data outside the EEA except as set out in clause 6 and Annex 3.

## 13. Liability, term and precedence

13.1 Liability under this DPA is subject to the limitations in the Agreement [*counsel to confirm*].

13.2 This DPA lasts as long as the Processor processes Client Personal Data. In case of conflict, this DPA prevails over the Agreement on data protection matters.

13.3 Governing law and jurisdiction: [as in the Agreement / law of [Member State]].

Signed for [Client]: name [ ], title [ ], date [ ]

Signed for Estefania Simon-Sasyk y Otro CB: name [ ], title [ ], date [ ]

---

## Annex 1 — Description of the processing

| | |
| --- | --- |
| Subject matter | Provision of a research assistant answering questions from a curated corpus of public sources and the Provider's analysis, with citations |
| Nature | Collection, storage, retrieval, transmission to a language model, display and deletion |
| Purpose | Authenticating [Client]'s users; answering their questions; keeping their conversation history for the retention period; serving the file list and downloads; security and audit of [Client]'s use; usage and cost accounting per customer |
| Data subjects | [Client]'s employees and contractors invited as users; tenant administrators |
| Categories of personal data | *DRAFT addition, Oct 22, 2026:* Client-supplied documents (clause 7A): personal data contained in them (typically names, roles and statements of authors, staff and people named), as declared by [Client]. Account data: email address, name if given, role, status, last sign-in time and method. Content: questions, conversation turns, answers, citations, feedback, model and reasoning setting chosen; any personal data a user types into a question. Workspace additional instructions written by [Client]'s administrators. Downloads: user, file, time. Audit metadata: user ID, event, time, workspace, model; no question or answer text. Technical: session tokens, IP address at sign-in |
| Special categories | None intended. [Client] instructs its users not to enter special-category data in questions, and does not supply it in documents unless agreed under clause 7A.1 |
| Frequency | Continuous while the Service is used |
| Duration | Term of the Agreement plus the deletion periods in clause 10 |
| Sign-in | Users sign in with a single-use link sent by email (valid 15 minutes, consumed only when the user presses the button on the landing page, limited per user). The email address is the only data sent to the email sub-processor. Tenant administrators also use a second factor [*pending: not yet configured in the Phase 1a build*] |

## Annex 2 — Technical and organisational measures

Drawn from the Provider's Compliance & Privacy Design Guide; SOC 2 criteria are indicative.

| Area | Measure |
| --- | --- |
| Customer isolation | Row-level security keyed on customer ID on every customer table, set per request from the authenticated user; per-customer cache keys; isolation tests in CI (CC6.1, C1.1) |
| Corpus access | Which corpus a workspace may search is set by the Provider server-side; the client never chooses datasets; entitlement test in CI (CC6.1, CC6.3) |
| Client-supplied documents (clause 7A; DRAFT, Oct 22, 2026, to be built in P1b-19 step 2) | Recorded per file with the supplying customer and the declaration reference; placed only in collections owned by that customer, checked by the application, the ingestion worker and the database; never de-duplicated with another customer's or the Provider's files; stored copies in a per-customer directory; withdrawn on request; deleted at termination with a certificate; passages wrapped as untrusted text in prompts (CC6.1, CC6.3, CC6.5, C1.1) |
| Data minimisation | Prompts carry no user, account or customer identifiers; tested on every build; context capped (CC6.7) |
| Model providers | Pinned model versions and an allow-list of endpoints checked at start-up; EU endpoints by default; external models only per clause 6, with zero-data-retention routing and data collection denied on every request (CC6.7, CC9.2) |
| Encryption | TLS 1.2+ in transit; encrypted volumes and encrypted backups at rest in Paris (CC6.1, CC6.7) |
| Logging | Logs hold metadata only; question, answer and prompt text, headers and tokens are never logged (CC7.2) |
| Retention | 30-day maximum chat history, per-customer shorter setting; download links single-use, 60 seconds (CC6.5) |
| Authentication | Single-use emailed links, 15-minute expiry, consumed only by a user action on the landing page so mail scanners cannot use them, rate-limited, no account enumeration; second factor for administrators [pending]; Provider operators on a separate internal tenant with hardware-key MFA (CC6.1, CC6.2) |
| Access control | Roles user and administrator per customer; Provider operator role cannot read conversations or messages; support access time-boxed and logged (CC6.3) |
| Audit | Append-only audit of sign-ins, administrative and operator actions, queries (metadata) and downloads; 12 months, write-once (CC7.2, CC7.3) |
| Abuse and extraction | Rate limits per user and customer; daily download cap; detection of bulk extraction (CC6.6) |
| Prompt safety | The model has no tools; public-source text is treated as untrusted input (CC6.8) |
| Change management | Reviewed pull requests, CI gates including isolation tests and evaluation (CC8.1) |
| Incident response | Runbook, breach notification per clause 9, annual tabletop (CC7.4, CC7.5) |
| Vendors | Sub-processor DPAs and zero-retention confirmations on file (CC9.2) |

## Annex 3 — Sub-processors

See `sub-processors.md` for the maintained list; at the date of this DPA. Client-supplied documents (clause 7A) add no sub-processor: they are stored and processed by Scaleway as below, and excerpts reach the language models listed here as part of prompts.

| Sub-processor | Purpose | Location | Safeguard |
| --- | --- | --- | --- |
| Scaleway SAS | Hosting, database, storage, backups | Paris, France | EU; Scaleway DPA |
| Scaleway SAS — Generative APIs | Language model inference (default) | Paris, France | EU; Scaleway DPA, zero-retention confirmation [pending] |
| Scaleway SAS — Transactional Email | Sending sign-in links and platform mail (email address and the link only) | Paris, France | EU; Scaleway DPA |
| Mailgun Technologies, Inc. (Sinch), EU region — **optional backup, only if activated** | Sending sign-in links and platform mail (email address and the link only) | EU region | Mailgun DPA with SCCs; EU region pinned; tracking off; the client is notified before activation per the sub-processor change clause |
| OpenRouter, Inc. — **only if external models are enabled** | Routing prompts to external models via EU endpoint | United States (EU endpoint) | SCCs; TIA |
| Amazon Web Services (Bedrock) — **only if enabled**, upstream of OpenRouter | Claude inference | [eu-west-1 Ireland — pending verification; otherwise United States] | Via OpenRouter; SCCs; TIA |
| Microsoft (Azure) — **only if enabled**, upstream of OpenRouter | GPT inference | [EU region — pending verification; otherwise United States] | Via OpenRouter; SCCs; TIA |

## Annex 4 — Acceptance of external models (optional)

[Client] accepts the external-models mode described in clause 6, with the sub-processors and transfer mechanism in Annex 3, for the workspaces of its tenant, with a monthly spend cap of **EUR [30.00]**.

Document reference: [ ] · Signed for [Client]: name [ ], title [ ], date [ ]

*The operator records this reference and date in the operator console when enabling the entitlement.*

---

## Notes for the owner (delete before sending)

1. **Roles.** The compliance guide's data map lists account data and audit logs under our controller role; this draft follows the later memo (processor for all of the client's user data, including accounts and the audit of its users). Pick one; if the guide's position is kept, clauses 1.4 and 10.3 to 10.4 change and the privacy notice must cover account data.
2. **Deletion wording (clause 10.2).** In Phase 1a the 30-day limit is applied at read time; rows are not yet purged (Phase 1b purge job). Do not promise deletion at 30 days until it runs.
3. **Retention floor.** The guide and architecture §7.2 say retention can go "down to 0"; the build allows 1 to 30 days (findings D7). This draft says 1 to 30.
4. **External-model region (clause 6.2).** Fill in only after the TIA verification; the fallback wording is the safe default.
5. **Notice periods and breach window** (clauses 5.2, 9.1) are placeholders for counsel.
6. **Downloads table retention** (`downloads` rows) is not yet set (backlog, Phase 1b); the audit event is 12 months.
7. **Annex 2 must match what is live at signature.** It lists the guide's controls. Not yet in place or not verified in Phase 1a: bulk-extraction detection (only rate limits and the download cap exist), the daily write-once export of the audit log, encrypted backups to Object Storage (the content store is a local volume until Phase 1b, findings D9), time-boxed support access, and operator hardware-key MFA (Authentik configuration, not checked by the API, findings A12). Mark these as planned with a date or remove them before signature.
8. **Client-supplied documents (clause 7A, Oct 22, 2026).** Drafted ahead of the build (P1b-19 step 2): do not offer clause 7A to a client until the step-2 isolation tests pass and the Annex 2 row is true. Open points in `open-questions.md` section J.
