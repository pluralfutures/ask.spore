# Paperwork Checklist — Before External Models Are Enabled

| | |
| --- | --- |
| Status | **DRAFT**: item 6 confirmed (Oct 20, 2026), item 9 done (Oct 21, 2026); everything else open |
| Date | Oct 19, 2026 |
| Author | Drafted for owner review (spec item P1a-15) |
| To finalise, the owner must | Work each line to "done", fill in the evidence location and date, and only then enable the external-models entitlement for any tenant in the operator console. The gate is a process rule; no code enforces it (findings A13). |

Rule: the external-models entitlement stays **off for every tenant** until every line below is "done". The operator console already refuses to enable it without an acceptance reference, an acceptance date and a spend cap (findings A13); it cannot check the rest.

Evidence is metadata and contracts only: no real queries, no secrets, no client documents in the repository. Contracts and letters are kept in **[the owner's document store, path]**; the repository records the reference and date.

| # | Item | Owner | Status | Evidence kept at |
| --- | --- | --- | --- | --- |
| 1 | OpenRouter DPA with the EU SCCs (module [2/3], version [ ]) accepted and filed; OpenRouter's published upstream vendor list and ZDR terms checked on the date of acceptance | Owner | Open | [document store]/vendors/openrouter/; reference and date in `transfer-impact-assessment.md` §5 and `sub-processors.md` |
| 2 | Scaleway DPA accepted and filed, naming the Paris region | Owner | Open | [document store]/vendors/scaleway/; reference in `sub-processors.md` |
| 3 | Scaleway's written zero-retention confirmation for Generative APIs naming our organisation ID, the models `deepseek-v4.1-flash` and `qwen3.8-27b` and the endpoint `api.scaleway.ai`, and stating how provider-side prompt caching is treated (findings M2, phase 0) | Owner | Open | [document store]/vendors/scaleway/; reference next to `config/models.toml` per its allow-list comment |
| 4 | Verification of findings C32 (TIA §10): region pinning in OpenRouter's provider-routing documentation; one real request per external model with its provider metadata recorded; Bedrock eu-west-1 and Azure EU region confirmed or the fallback adopted; both endpoints on OpenRouter's ZDR list; Azure abuse monitoring checked | Owner with engineering (P1a-16) | Open | `design/specs/phase-1a-findings.md` (new row closing C32) and `transfer-impact-assessment.md` §10 |
| 5 | Transfer impact assessment finalised: §4A or §4B stated, SCC details filled in, review date set, signed | Owner | Drafted (`transfer-impact-assessment.md`) | `design/compliance/transfer-impact-assessment.md` |
| 6 | GDPR roles position confirmed (processor for client user data, controller for corpus and own logs) | Owner | Confirmed Oct 20, 2026 | Decision recorded in the compliance guide addendum |
| 7 | Client DPA reviewed by counsel and signed by [Client], including Annex 4 (acceptance of external models, spend cap EUR 30/month) | Owner, counsel | Drafted (`client-dpa-draft.md`) | Signed copy in [document store]/clients/[Client]/; reference and date entered in the operator console (stored on the entitlement and in the audit event) |
| 8 | Sub-processor list final and given to [Client] with the DPA | Owner | Drafted (`sub-processors.md`) | `design/compliance/sub-processors.md` |
| 9 | Qwen reasoning switch confirmed with one real call on Scaleway (`reasoning_effort` `"none"` and `"medium"`, findings C26) | Engineering | **Done** Oct 21, 2026: `none` and `medium` both answer on Scaleway; reasoning hidden | `design/specs/phase-1a-findings.md` §10, row F8 (usage metadata only) |
| 10 | `anthropic/claude-opus-5.5` confirmed with one real call through `eu.openrouter.ai` with the production request shape (pin, `allow_fallbacks: false`, `zdr: true`, `data_collection: "deny"`); serving provider recorded | Engineering | Open, **deferred** by owner decision Oct 21, 2026 (findings §10); external entitlement never granted | Same; can be the same call as item 4 |
| 11 | `openai/gpt-6.1-sol` confirmed the same way | Engineering | Open, **deferred** by owner decision Oct 21, 2026 (findings §10) | Same |
| 12 | Spend cap of EUR 30.00 (3,000 cents) set for [Client] in the operator console when enabling | Operator | Open (after 1 to 11) | Audit event `operator.entitlements_changed` |
| 13 | Email: sending domain verified in Scaleway Transactional Email (fr-par; SPF, DKIM, MX, DMARC), quota checked, covered by item 2. Mailgun EU backup: DPA with SCCs accepted and filed, EU region, tracking off, **before** the backup is ever switched on (owner decision Oct 20, 2026) | Owner | Open | [document store]/vendors/scaleway/ and /vendors/mailgun/; reference in `sub-processors.md` |

Real calls in items 4 and 9 to 11 use a synthetic question, never a client query, and record only metadata (provider, model, token counts, status), never the prompt or answer text.

## Not required for the gate, but due before launch to the client

| Item | Owner | Status |
| --- | --- | --- |
| Trust page published (`trust-page.md`) with the outcome of item 4 | Owner | Drafted |
| Public privacy notice covering public-source personal data and our controller processing | Owner | Open |
| Second factor for tenant administrators configured in Authentik | Engineering | **Done** Oct 22, 2026 (blueprint MFA stage and group, findings 1b §8 0.4); checked live: enrolment and code (2.3, 6.2), refusal of an admin link without it (close-out, Oct 23) |
| DMARC on the organisation domain (`myceliumgastronomy.com`, the parent of the sending host) moved from `p=none` to `p=quarantine` (P1c-05), after **seven consecutive days of clean aggregate reports** for the platform mail: every message from Scaleway Transactional Email (fr-par) passes DMARC (aligned DKIM or SPF) and nothing else sends as the domain unannounced. The session checks the reports' summary as counts only (messages, pass and fail per sending source); the owner makes the DNS change. Procedure: `infra/README.md`, "Mail domain policy (P1c-05)" | Owner | Open (`p=none` since the Phase 1b release 2.1). Phase 1c release 6.3 (Oct 23, 2026): the record has **no `rua=` tag**, so no aggregate report has been sent; the owner adds `rua=mailto:<mailbox>` first, and the clean week counts from the first report (findings 1c F6) |
| Deletion wording in the DPA matched to the build (read-time expiry until the Phase 1b purge job) | Owner | Open. The build now supports clause 10.2 option (a) for the database: the daily retention purge is live (findings 1b §8 6.1) and the termination purge with its certificate was run on Oct 23 (6.3), and again at the Phase 1c release close-out (`ssotest2`, certificate `COD-20261023-8194328d`); backups age out per the owner-run backup retention. The wording choice and the [7]/[35]-day figures stay the owner's. Phase 1c release 6.1: no volume backup is visible on the Instance, so the wording's backup retention must be checked against wherever the backup actually lives (backlog, restore test) |
| Credentials rotated: every default or example password on the Instance (P1c-03) | Owner | **Done** Oct 23, 2026 (Phase 1c release 0.1; procedure `infra/README.md` "Credentials rotation"; `check-credentials.py` ok) |
| Restore test of the nightly backup, and the nightly content-store copy (P1c-12) | Owner, engineering | Open: moved to the backlog at the Phase 1c release 6.1 (owner decision, Oct 23, 2026): no volume backup visible on the Instance. Due before the first client user |

## Phase 1b document set

Added Oct 21, 2026 (spec item P1b-09). Each document is a draft for owner and counsel review under `design/compliance/`. "Counsel review" says whether counsel must review before the document is used; "Filed" is the date and location of the approved version (signed copies in [document store]). The open questions across the set are collected in `open-questions.md`. The P1b-10 consent gate shows the privacy notice and the AI transparency note; they must be approved before that gate goes live.

| # | Document | File | Owner | Counsel review | Status | Filed |
| --- | --- | --- | --- | --- | --- | --- |
| D1 | Public privacy notice (Art. 13, Art. 14 section for people named in indexed sources) | `privacy-notice.md` | Owner | Required | Drafted | [date, location] |
| D2 | Terms of service / MSA with order form (Annex A) | `terms-of-service.md` | Owner | Required | Drafted | [date, location] |
| D3 | Information security policy | `policy-information-security.md` | Owner (security lead) | Optional | Drafted | [date, location] |
| D4 | Access control policy | `policy-access-control.md` | Owner (security lead) | Optional | Drafted | [date, location] |
| D5 | Change management policy | `policy-change-management.md` | Owner (engineering) | Optional | Drafted | [date, location] |
| D6 | Incident response policy | `policy-incident-response.md` | Owner (security lead) | Optional | Drafted | [date, location] |
| D7 | Vendor management policy | `policy-vendor-management.md` | Owner (security lead) | Optional | Drafted | [date, location] |
| D8 | Data retention and disposal policy | `policy-data-retention-disposal.md` | Owner | Recommended (must match the DPA) | Drafted | [date, location] |
| D9 | Business continuity policy | `policy-business-continuity.md` | Owner | Optional | Drafted | [date, location] |
| D10 | Records of processing (Art. 30, controller and processor registers) | `records-of-processing.md` | Owner | Recommended | Drafted | [date, location] |
| D11 | DPIA for the platform | `dpia.md` | Owner | Required | Drafted | [date, location] |
| D12 | Legitimate-interest assessment for the public-source corpus | `legitimate-interest-assessment.md` | Owner | Required | Drafted | [date, location] |
| D13 | Incident runbook with breach-notification templates | `incident-runbook.md` | Owner (security lead) | Recommended (notification windows) | Drafted | [date, location] |
| D14 | Risk register | `risk-register.md` | Owner (security lead) | Optional | Drafted | [date, location] |
| D15 | EU AI Act technical documentation | `ai-act-technical-documentation.md` | Owner | Required (classification and Art. 50) | Drafted | [date, location] |
| D16 | AI transparency note for users | `ai-transparency-note.md` | Owner | Recommended | Drafted | [date, location] |
| D17 | Onboarding pack (IT and SSO sheet, email templates, admin MFA guidance, first-week checklist) | `onboarding-pack.md` | Owner | Optional | Drafted | [date, location] |
| D18 | Pre-filled security questionnaire | `security-questionnaire.md` | Owner (security lead) | Optional | Drafted | [date, location] |
| D19 | Offboarding pack (termination and deletion procedure, certificate of deletion, deactivation and exit notices) | `offboarding-pack.md` | Owner | Recommended (deletion wording must match the DPA) | Drafted | [date, location] |
| D20 | Open questions for the owner and counsel | `open-questions.md` | Owner | Required | Open | n/a |
| D21 | Client-supplied documents addendum (architecture §15, compliance guide Oct 22): DPA clause 7A, terms §6A and A.8, privacy notice §13, and the changes across D1, D10 to D12, D14, D15, D17 to D19, the TIA, the sub-processor list and the trust page (P1b-19 step 1). Not for the test client | the files named | Owner | Required (warranty, indemnity, processor role) | Drafted Oct 22, 2026 | [date, location] |
