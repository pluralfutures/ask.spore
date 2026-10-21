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
| A1 | Legal entity name, form, address and company number of the contracting party (Plural Futures or Mycelium Gastronomy?) | all | |
| A2 | **C** Is a DPO required, or is a named privacy contact enough? Who is it? | privacy-notice, records-of-processing | |
| A3 | Lead supervisory authority and Member State | privacy-notice, dpia, incident-runbook, policy-incident-response | |
| A4 | Contact addresses: privacy, security, takedown, support; incident lead phone, a deputy, counsel contact | privacy-notice, incident-runbook, policy-business-continuity, onboarding-pack | |
| A5 | Named security lead, given the owner holds every internal role today | policy-information-security, policy-* | |
| A6 | Client-facing product name and hostname: the sign-in template hard-codes "ask.spore" and `askspore.myceliumgastronomy.com` | onboarding-pack, trust page | |

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
| C8 | Do sign-in links stay on for [Client] once SSO is live? | dpia, onboarding-pack | |

## D. Facts to confirm on the Instance and with vendors

| # | Question | Files | Answer |
| --- | --- | --- | --- |
| D1 | Are the Instance's Block Storage volumes encrypted at rest? (DPA Annex 2 already says "encrypted volumes") | policy-information-security, privacy-notice, security-questionnaire | |
| D2 | Is hardware-key MFA configured for operators in Authentik (the API does not check it, findings A12)? | policy-access-control, security-questionnaire | |
| D3 | Docker log rotation period on the Instance (target 30 days); automatic OS security updates and fail2ban on; Scaleway DDoS protection | records-of-processing, policy-data-retention-disposal, security-questionnaire | |
| D4 | Backups: retention (30 days recommended), first restore test date; RTO and RPO; Scaleway support plan; deputy for emergency account access | policy-business-continuity, incident-runbook, offboarding-pack, security-questionnaire | |
| D5 | Scaleway DPA reference, security evidence to file (SOC 2 or ISO 27001), expected date of the zero-retention letter (M2) | policy-vendor-management, security-questionnaire | |
| D6 | Mailbox provider and accounting tools used by the owner, and their location (records of processing) | records-of-processing | |
| D7 | With Mistral inactive and no DPA in force, a Scaleway inference outage means no answers. Accept, or contract a second EU provider? | incident-runbook, policy-business-continuity | |

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
