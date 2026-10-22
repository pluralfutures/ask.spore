# Open Questions for the Owner and Counsel — Phase 1b Document Set — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT**: every question open |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | none; the placeholders of each document are listed in its own header |
| To finalise, the owner must | Answer each question, or pass it to counsel where marked; record the answer and date in the last column; then update the documents named and their row in `paperwork-checklist.md` ("Phase 1b document set"). |

---

Only the owner or counsel can answer these. Duplicates across the documents are merged; the files affected are named. "C" marks a question for counsel.

## A. Entity, contacts and authorities

| # | Question | Files | Answer |
| --- | --- | --- | --- |
| A1 | Legal entity name, form, address and company number of the contracting party (Plural Futures or Mycelium Gastronomy?) | all | **Answered Oct 21, 2026:** Estefania Simon-Sasyk y Otro CB (comunidad de bienes), trading as Mycelium Gastronomy Network, NIF E19824093. Filled into every draft; the registered address is still open. See A7 and A8 |
| A2 | **C** Is a DPO required, or is a named privacy contact enough? Who is it? | privacy-notice, records-of-processing | |
| A3 | Lead supervisory authority and Member State | privacy-notice, dpia, incident-runbook, policy-incident-response | |
| A4 | Contact addresses: privacy, security, takedown, support; incident lead phone, a deputy, counsel contact | privacy-notice, incident-runbook, policy-business-continuity, onboarding-pack | |
| A5 | Named security lead, given the owner holds every internal role today | policy-information-security, policy-* | |
| A6 | Client-facing product name and hostname: the sign-in template hard-codes "ask.spore" and `askspore.myceliumgastronomy.com` | onboarding-pack, trust page || **Answered Oct 21, 2026:** SporeBot at `askspore.myceliumgastronomy.com`. Filled in; the Authentik template and email subject still say "ask.spore" and must change before the first client invite (infra change) |
| A7 | Registered address of the CB, for the notice, terms, DPA and records | all | |
| A8 | **C** A comunidad de bienes has no legal personality separate from its members (the comuneros), who answer for its debts. Is the CB the right contracting party for client contracts and the controller named in the notice, or should a company be formed first? Who signs for it? Follows from this: the lead supervisory authority is likely the AEPD (Spain) and Spanish law and courts the likely default (A3, B3); confirm | terms-of-service, privacy-notice, client-dpa-draft, records-of-processing | |

## B. Contract terms (C for all)

| # | Question | Files | Answer |
| --- | --- | --- | --- |
| B1 | MSA with order form (as drafted) or click-through terms? Does the P1b-10 first-login gate also carry the terms, or only the privacy notice and transparency note? | terms-of-service, onboarding-pack | |
| B2 | Liability cap, and a separate higher cap for data-protection and confidentiality breaches? | terms-of-service | |
| B3 | Governing law, jurisdiction, term, renewal, notice period, payment terms | terms-of-service | |
| B4 | Prices: per seat, platform fee, onboarding and SSO setup, external-model usage (included or pass-through) | terms-of-service Annex A | |
| B5 | Support channel, hours, first-response time; state an availability target at all on a single Instance? | terms-of-service | |
| B6 | Export window at termination: the ToS drafts [10] working days on a request [15] days before the end, the offboarding pack proposes 30 days. Pick one; export is a manual operator job (no export feature is built), so offer it at all given 30-day retention? Format and delivery method? | terms-of-service, offboarding-pack | |
| B7 | Client breach-notification window ([48] hours in DPA clause 9.1) and sub-processor notice period ([30] days, clause 5.2) | incident-runbook, policy-incident-response, policy-vendor-management | |
| B8 | Wording of the acceptable-use ban on special-category data and on Annex III (high-risk) uses without telling us first | terms-of-service | |
| B9 | Customer-facing names of the three `cc` workspaces in Annex A, and which files carry `cc-shared` (P1b-13d) | terms-of-service | |

## C. Things the built system does not do yet, where a document makes a promise

| # | Question | Files | Answer |
| --- | --- | --- | --- |
| C1 | **Audit disposal.** Audit events are promised for 12 months, but the trigger rejects DELETE for every role, so nothing can end them. Choose: a controlled disposal procedure (who approves it), monthly partitions dropped by the owner, or a longer period stated in the DPA. Affects terminated tenants too | policy-data-retention-disposal, privacy-notice, records-of-processing, offboarding-pack, incident-runbook | |
| C2 | **Query rate limits and bulk-extraction detection** are not built and in no spec, but the DPA Annex 2 and the trust page imply them. Plan them (backlog item) or remove the claims? | risk-register R-08, security-questionnaire | |
| C3 | **Time-boxed support access** (architecture §7.4) is in no spec. Plan it, or drop it from DPA Annex 2? | policy-access-control | |
| C4 | **Tenant admin audit-log download** (architecture §7.2, the P1b-10 test) has no route and no spec item. Add it to Phase 1b, or provide exports on request? | security-questionnaire, onboarding-pack | |
| C5 | **Suspension** exists in the schema but has no console or CLI action (schema owner only). Add an audited action? | offboarding-pack | |
| C6 | Until P1b-14 ships: who writes and approves the manual per-tenant purge, and may a certificate of deletion say "manual procedure"? **C** Is the certificate's retained-items list (audit 12 months, backups 30 days, billing records) consistent with DPA clause 10.5? | offboarding-pack | |
| C7 | Until P1b-03 and P1b-04 ship: can the 30-day erasure window and 10-working-day takedown be met by hand? Are new crawled sites added only after a manual reviewer check, or held? Does [Client] go live before P1b-03 and P1b-14, accepting medium residual risk (DPIA R2, R8)? | privacy-notice, legitimate-interest-assessment, dpia | |
| C8 | Do sign-in links stay on for [Client] once SSO is live? | dpia, onboarding-pack || **Answered Oct 21, 2026:** no. Links are switched off for a tenant once its SSO is live, unless the operator specifically enables them for that tenant (dpia, onboarding-pack updated) |

## D. Facts to confirm on the Instance and with vendors

| # | Question | Files | Answer |
| --- | --- | --- | --- |
| D1 | Are the Instance's Block Storage volumes encrypted at rest? (DPA Annex 2 already says "encrypted volumes") | policy-information-security, privacy-notice, security-questionnaire | |
| D2 | Is hardware-key MFA configured for operators in Authentik (the API does not check it, findings A12)? | policy-access-control, security-questionnaire | |
| D3 | Docker log rotation period on the Instance (target 30 days); automatic OS security updates and fail2ban on; Scaleway DDoS protection | records-of-processing, policy-data-retention-disposal, security-questionnaire | |
| D4 | Backups: retention (30 days recommended), first restore test date; RTO and RPO; Scaleway support plan; deputy for emergency account access | policy-business-continuity, incident-runbook, offboarding-pack, security-questionnaire | |
| D5 | Scaleway DPA reference, security evidence to file (SOC 2 or ISO 27001), expected date of the zero-retention letter (M2) | policy-vendor-management, security-questionnaire | |
| D6 | Mailbox provider and accounting tools used by the owner, and their location (records of processing) | records-of-processing | |
| D7 | With Mistral inactive and no DPA in force, a Scaleway inference outage means no answers. Accept, or contract a second EU provider? | incident-runbook, policy-business-continuity || **Answered Oct 21, 2026:** backup is OpenRouter, routed only to EU-served models with zero data retention. Recorded as planned, not built; see D8 |
| D8 | OpenRouter as the inference backup for every tenant conflicts with the CLAUDE.md rule (OpenRouter only for tenants with the external-models entitlement) and DPA clause 6.1 (default Scaleway only). Should it (a) be a backup only for tenants that have accepted external models, which the current rules already allow, or (b) cover every tenant, which needs the rule, architecture §14 and Stack Decision changed, a verified EU-only routing pin (as C32), DPA clause 6, sub-processor notice to clients and a TIA update (OpenRouter is a US company)? | policy-business-continuity, incident-runbook, risk-register R-33 | |

## E. Retention values

| # | Question | Files | Answer |
| --- | --- | --- | --- |
| E1 | Retention of expired sign-in link rows (not in P1b-14 as written), licence files after a source is removed | policy-data-retention-disposal | |
| E2 | `usage_ledger` (tenant, month, model, tokens, cost; no user): confirm it is our own billing record as controller and not user personal data; retention 7 years or the statutory accounting period? | records-of-processing | |
| E3 | Retention of support, privacy and takedown correspondence (drafted [2 years] in the notice, 3 years in the records) and of business contacts after the contract | privacy-notice, records-of-processing | |
| E4 | Public website: analytics, cookies, contact form, and the legal basis for each | privacy-notice | |

## F. Corpus, licensing and GDPR basis

| # | Question | Files | Answer |
| --- | --- | --- | --- |
| F1 | **Third-party downloads.** By the decision of Oct 20, 2026 the third-party test-corpus rows are downloadable as the manifests declare. Is a redistribution licence basis recorded per source, or should each flagged row be reviewed before the notice and terms say "only where its licence allows"? | risk-register R-07, privacy-notice, terms-of-service, dpia, incident-runbook | |
| F2 | **C** Legitimate interests as the basis for people named in sources: does counsel accept the balancing test and the Art. 14(5)(b) disproportionate-effort reasoning? | legitimate-interest-assessment, privacy-notice | |
| F3 | **C** Prior consultation (Art. 36) not needed: confirm against the lead authority's DPIA list | dpia | |
| F4 | **C** Is notice plus in-app acceptance the right mechanism for the P1b-10 gate (it is not GDPR consent as a legal basis)? | onboarding-pack, privacy-notice | |

## G. EU AI Act (C for all)

| # | Question | Files | Answer |
| --- | --- | --- | --- |
| G1 | Confirm the classification: limited-risk AI system; we are its provider, not a general-purpose model provider; customers are deployers | ai-act-technical-documentation | |
| G2 | Does Art. 50(2) machine-readable marking apply to in-app answers with citations, which exceptions apply, and from what date, including any changes from the Digital Omnibus? No machine-readable marking is built | ai-act-technical-documentation, risk-register R-27 | |
| G3 | Tell customers in the terms about their own Art. 50(4) duty when they publish generated text on matters of public interest? | ai-act-technical-documentation, terms-of-service | |
| G4 | Art. 4 AI literacy: owner, training record, review date | ai-act-technical-documentation | |
| G5 | Keep "external models are not enabled for any organisation" in the transparency note, or drop it so the text survives enabling? | ai-transparency-note | |

## H. People, governance and assurance

| # | Question | Files | Answer |
| --- | --- | --- | --- |
| H1 | Who reviews pull requests while there is one internal person; is an independent Claude review session acceptable evidence for CC8.1; emergency-change review window (drafted 2 working days)? | policy-change-management | |
| H2 | First quarterly access review date; is self-review acceptable while one person holds every role? Accept the key-person risk or plan a second internal user? | policy-access-control, risk-register R-25 | |
| H3 | HR answers: background checks, confidentiality terms, annual training, staff count, insurance; needed before the SOC 2 window? | policy-information-security, security-questionnaire | |
| H4 | Dates: pentest, vulnerability scanning, first tabletop, SOC 2 observation window start | security-questionnaire, incident-runbook, policy-incident-response | |
| H5 | Confirm or change the risk ratings; set the review date | risk-register | |

## I. Onboarding mechanics

| # | Question | Files | Answer |
| --- | --- | --- | --- |
| I1 | How client IT delivers SSO client secrets and SAML keys to us | onboarding-pack | |
| I2 | How we verify domain control before registering a verified domain (DNS TXT record or written confirmation) | onboarding-pack | |
| I3 | Admin MFA reset procedure and the client contact who confirms a reset | onboarding-pack | |
| I4 | Who signs certificates of deletion; do user deactivation notices come from the client admin or from us? | offboarding-pack | |

## J. Client-supplied documents

Added Oct 22, 2026 (P1b-19 step 1, owner decision 11; architecture §15, compliance guide addendum of Oct 22). **DRAFT**: every question open. None affects the test client `cc`, which supplies nothing.

| # | Question | Files | Answer |
| --- | --- | --- | --- |
| J1 | **C** Is our role for personal data in client-supplied files processor (as drafted), and is the client then solely responsible for Art. 14 towards people named in its files? Is a mixed workspace (client files plus our public content, controller) acceptable as drafted, with one prompt carrying data under both roles? | client-dpa-draft 1.3(b), 7A.4; privacy-notice §13; records-of-processing; TIA §2 | |
| J2 | **C** Warranty and indemnity (terms §6A.2, §6A.3): wording, whether the indemnity is capped or uncapped, and how it sits with the liability cap in §11 | terms-of-service | |
| J3 | **C** May we tell a person who writes to us which client supplied a document that names them, or only that we forwarded the request (privacy notice §13)? | privacy-notice | **Answered by the owner, Oct 22, 2026:** rather not. Drafted as: we forward the request and say so; we name the customer only with its agreement or when a court or authority requires it. **Counsel still to confirm** (summary of the EU and US position given to the owner on Oct 22: no general duty on a processor to name the controller; the Art. 14(2)(f) and 15(1)(g) source duties are the client's as controller; disclosure can be compelled by a supervisory authority (Art. 58), by a court in IP proceedings (Enforcement Directive Art. 8) or, in the US, by a DMCA §512(h) or civil subpoena) **Owner agreed with the draft wording, Oct 22, 2026.** Counsel to confirm only the legal summary. |
| J4 | **C** When a third party claims a client file infringes its rights, may we withdraw it without the client's instruction (terms §6A.6, DPA 7A.5), and does withdrawing on our own initiative sit with the processor role? | terms-of-service, client-dpa-draft | **Answered by the owner, Oct 22, 2026:** yes, on receipt of a third party's notice (expected to be rare). Terms §6A.6, DPA 7A.5 and architecture §15.7 updated. **Counsel still to confirm** the processor-role point and that the DSA hosting rules (notice and action, statement of reasons to the client) are met |
| J5 | Withdrawal window on the client's request: [5] working days as drafted, or the 10 working days of the publisher takedown SLA? | terms-of-service, client-dpa-draft, onboarding-pack, security-questionnaire | |
| J6 | Intake channel: how clients send files ([secure transfer method]: a shared folder in the owner's document store, an SFTP drop, encrypted email?), and who deletes the transfer copy. A tenant-side upload page is in no phase; add it to the backlog? | architecture §15.2, terms A.8, onboarding-pack 1.8 | **Answered by the owner, Oct 22, 2026:** upload page added to `backlog.md`. The interim channel ([secure transfer method]) and who deletes the transfer copy are **still open** |
| J7 | Limits: [max file size] and [max files per batch]; Markdown and HTML accepted at all? | architecture §15.3, terms 6A.1 | |
| J8 | Malware scan of supplied files before parsing: required, and with which tool (a new component, so a Stack Decision change), or accept the internal-network parser as the control? | architecture §15.3, risk-register R-37, security-questionnaire 17.10 | |
| J9 | "Shared tags": confirm the reading that a client-supplied file may sit in a tag owned by its tenant that several of **that tenant's** workspaces share (as `cc-shared` does for `cc`), and never in a platform tag available to more than one tenant | architecture §15.4 | |
| J10 | Stored excerpts after a client withdraws its own file: keep them labelled "withdrawn" in the client's conversations (decision 5 for non-licence withdrawals), or blank them too, since they are the client's confidential text? | architecture §15.7 | **Answered by the owner, Oct 22, 2026:** kept, labelled "withdrawn". Architecture §15.7 and DPA 7A.5 updated; third-party rights withdrawals still blank them (decision 5) |
| J11 | Provenance shown and sent to the model for client files: may the declared publisher be the client's own name (a tenant-supplied identifier in the prompt, permitted as drafted like the workspace instructions), or should it be a neutral label such as "Your organisation"? | architecture §15.9, compliance guide addendum | |
| J12 | Does a client that supplies documents and accepts external models need a separate, explicit acceptance that excerpts of its own (possibly confidential) files go to OpenRouter and its upstream vendors, beyond DPA Annex 4? | client-dpa-draft Annex 4, transfer-impact-assessment §3 | |
| J13 | Special-category data in client files: barred unless agreed (DPA 7A.1, as drafted), or barred outright? | client-dpa-draft, dpia R13 | |
| J14 | Register rows after termination: erase descriptive fields and keep ID, tenant and withdrawal date (as drafted), or delete the rows, with audit events keeping only source IDs? Retention of client declarations ([limitation period]) | architecture §15.8, offboarding-pack, records-of-processing C9 | |
| J15 | A client that asks for a dedicated index or RAGFlow instance: decline (shared instance with tenant-owned datasets, as drafted), or price it as an option? *Clarified for the owner, Oct 22:* today every client's content sits in one RAGFlow installation (one search engine, one file store), separated into per-tag collections, with our application deciding which collections a workspace may search. A "dedicated index" means a separate RAGFlow installation (its own server or containers, search index and file store) for one client, so its files never share a system with another's. Some security teams ask for it; it costs roughly a second retrieval host (about EUR 150 a month at today's sizing) plus its upgrades, backups and evals, and changes the "logical isolation" decision of Oct 17. | architecture §15.4, compliance guide | **Answered by the owner, Oct 22, 2026:** refuse, unless a signed contract obliges us to provide one. Architecture §15.4 and the compliance guide addendum updated |
| J16 | Evaluation on a client's own corpus: allowed only with the client's agreement and metrics only, as drafted? Should the terms say so? *Clarified Oct 22:* the owner's existing practice, reviewing each file the client sends for relevance to the workspace's purpose, is now written into the intake review (architecture §15.2, terms §6A.1) and needs no extra agreement. The open question is only about automated quality evaluation (eval sets and scores, architecture §9) run on a client's files: "with its agreement" because the test questions are written from its confidential files; "metrics only" because only scores go into the repository, never questions, answers or file text (CLAUDE.md) | architecture §15.9 | **Answered by the owner, Oct 22, 2026:** yes, allowed by default unless the client's contract excludes it. Terms §6A.5 and A.8 (opt-out row), DPA 7A.2, architecture §15.9, compliance guide and security questionnaire 17.3 updated |
| J17 | Pricing for document supply (per document, per GB, onboarding fee) for the order form | terms-of-service Annex A | |
