# Risk Register — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [security lead name], [date]; "[confirm]" marks a fact to check |
| Revision | Oct 22, 2026, **DRAFT**: R-34 to R-37, client-supplied documents (P1b-19 step 1, architecture §15) |
| To finalise, the owner must | (1) confirm or change each likelihood and impact; (2) accept the residual risks marked "accept?" or plan a treatment; (3) set the review date; (4) sign. |

---

Scale: likelihood and impact are Low, Medium or High, judged for the current platform (one Instance, one test client, one internal person). "Planned" cites the spec item that treats the risk; "—" means nothing is planned yet. The owner holds every risk today. Reviewed every quarter and on any change listed in `policy-vendor-management.md` or `policy-change-management.md`. SOC 2 CC3.2 and CC9.1 (indicative).

| ID | Risk | Likelihood | Impact | Controls in place | Planned (spec item) | Owner | Review |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R-01 | **Cross-tenant query leakage**: one client sees another's questions, answers or cached answers | Low | High | Forced RLS on 18 tenant tables; tenant-prefixed cache; token bound to tenant; isolation review signed (findings §10, §12) | Isolation tests extended to new tables (P1b-16) | Owner | [date] |
| R-02 | **Cross-tenant corpus access**: a workspace retrieves another package's documents | Low | Medium | Dataset IDs resolved server-side; client IDs rejected (422); `select_context` drops out-of-package chunks | Operator console shows only the tenant's tags; API refuses foreign tags (P1b-12) | Owner | [date] |
| R-03 | **Prompt injection via crawled pages** or forged passages | Medium | Medium | No tools; untrusted wrapping of `html` and `markdown` passages; guardrail eval at 100 on every block except 03 (findings §11 G6–G9) | Crawl controls (P1b-04); eval gate in CI (P1b-15) | Owner | [date] |
| R-04 | **System-prompt leakage** | Low | Low | Secrecy rule, fixed refusal under the leak length (G3); guardrail block 15 at 100 | Output scanner for leaked prompt (architecture §8) — not planned in Phase 1b | Owner | [date] |
| R-05 | **Unsupported or hallucinated answers** presented as sourced | Medium | Medium | `corpus_only` answers withheld until they cite (G6); general-knowledge sentences marked; "AI-generated, verify against cited sources" notice; eval v1 no regression (G9) | Eval gate in CI (P1b-15); terms disclaimer (`terms-of-service.md`) | Owner | [date] |
| R-06 | **Licence breach**: ingesting or redistributing content against its licence or TDM reservation | Medium | High | Source register with licence basis; robots.txt honoured by the crawler; downloads only where `downloadable` is set | Approval flow (P1b-01); TDM header and per-site rules (P1b-04); takedown within 10 working days (P1b-03) | Owner | [date] |
| R-07 | **Third-party files downloadable on the test corpus**: by owner decision of Oct 20, 2026 the third-party rows are downloadable as the manifests declare, so a wrong flag redistributes a publisher's file from our domain | Medium | High | Per-source flag; single-use 60 s links; 50 per user per day; `download` audit event | Per-source licence file (P1b-01); review of every flagged third-party row — **accept?** | Owner | [date] |
| R-08 | **Bulk extraction** of corpus content through questions or downloads | Medium | Medium | Download cap and audit; excerpts only in citations | Detection rules and per-user query rate limits: not planned (open) | Owner | [date] |
| R-09 | **Personal data in public sources** (named people, special categories) | Medium | Medium | Public sources only; erasure by document removal | Special-category skip at crawl (P1b-04); takedown queue (P1b-03); LIA and privacy notice (`legitimate-interest-assessment.md`, `privacy-notice.md`) | Owner | [date] |
| R-10 | **Vendor retention change** (Scaleway Generative APIs stops honouring no retention) | Low | High | Allow-list; pinned models | Written zero-retention letter (checklist item 3, open, findings M2); annual check | Owner | [date] |
| R-11 | **External provider retention change** (OpenRouter policy) | Low | High | ZDR and `data_collection: deny` on every request, tested; entitlement off for every tenant | Gate in `paperwork-checklist.md`; TIA review triggers | Owner | [date] |
| R-12 | **Upstream vendor outside the published ZDR routing** (Bedrock or Azure region or abuse monitoring) | Medium | High | Provider pin, fallbacks off | Verification C32 (P1b-13b) before any enabling | Owner | [date] |
| R-13 | **Model cost overrun** | Low | Low | Per-tenant spend cap with hard stop and fallback (`model.fallback`); 80 and 100 percent notices | Spend view per tenant (P1b-12) | Owner | [date] |
| R-14 | **Email provider retention or region change** | Low | Medium | Scaleway fr-par under the Scaleway DPA; only the address and link are sent; Mailgun backup inactive | Platform mail module (P1b-11) | Owner | [date] |
| R-15 | **Web-search provider retention change** (Phase 2) | — | — | Mode not built | Phase 2; listed now as the guide requires | Owner | [date] |
| R-16 | **Licensed content displaced by web content** in answers (Phase 2) | — | — | Mode not built | Phase 2; web citations labelled separately | Owner | [date] |
| R-17 | **Single-host outage** (Instance, disk or zone) | Medium | High | Compose rebuild from the repository | Two-host deployment in backlog; RTO and RPO in `policy-business-continuity.md` | Owner | [date] |
| R-18 | **Backup not restorable** | Medium | High | Owner-run nightly backups (recommended setup) | Restore test recorded in Phase 1b findings | Owner | [date] |
| R-19 | **Secrets in env files** on the Instance (provider keys, RAGFlow service key, Authentik tokens, email credential) | Medium | High | Not in the repository; app refuses to start without them | Secret Manager in backlog; rotation procedure — open | Owner | [date] |
| R-20 | **Bodies leaking to logs** through exceptions (findings §12 defect) | Low | High | Fixed in e0435c1: `hide_parameters=True`, ErrorBoundary, control characters refused; `test_no_bodies_in_errors` | Mail logs tested (P1b-11) | Owner | [date] |
| R-21 | **Operator console misuse**: a save applied to the wrong tenant (findings §10 F2) | Medium | Medium | Audited with before and after; reverted | One tenant per page, tenant-named saves (P1b-12) | Owner | [date] |
| R-22 | **Sign-in link consumed by a mail scanner** | Medium | Low | Link consumed only by a POST from the landing page | Live test with the client's scanner (P1b-13a); mail-scanner note in `onboarding-pack.md` | Owner | [date] |
| R-23 | **Account takeover through a compromised mailbox** | Low | High | 15-minute single-use links bound to the requesting browser; 5 per window | Client SSO (P1b-07); admin MFA (P1b-08); per-IP limit (P1b-08) | Owner | [date] |
| R-24 | **Tenant or staff names in workspace prompts** sent to the model | Medium | Low | Permitted tenant-authored exception; `workspace.prompt_tenant_name_match` flag to the operator | — (accepted by design, compliance addendum Oct 18) | Owner | [date] |
| R-25 | **Key-person dependency**: one internal person holds every role; no separation of duties, no second reviewer, no on-call | High | High | Independent review sessions for releases; self-approval audited (P1b-01) | Second internal user — not planned; deputy access in `policy-business-continuity.md` — **accept?** | Owner | [date] |
| R-26 | **Merging with red CI** (findings §10 F9) | Medium | Medium | CI, Eval and Guardrails workflows | Branch protection with required checks (P1b-13c) | Owner | [date] |
| R-27 | **EU AI Act transparency gap**: generated text not marked in a machine-readable way (Art. 50(2)) | Medium | Medium | Visible "AI-generated" notice and mode banners | See `ai-act-technical-documentation.md`; counsel to confirm the duty and dates — open | Owner | [date] |
| R-28 | **Audit log disposal impossible**: the trigger rejects DELETE for every role, so the 12-month retention cannot be applied | High | Low | Append-only table | Procedure to choose (`policy-data-retention-disposal.md` §4) — open | Owner | [date] |
| R-29 | **Chat history kept as rows past 30 days** (read-time expiry only) | High | Medium | Unreachable on every route (tested) | Purge job (P1b-14) | Owner | [date] |
| R-30 | **No vulnerability scanning or pentest**; images not pinned by digest | Medium | Medium | Pinned image tags; only Caddy exposed | Digest pins (P1b-15); scanning and pentest — not scheduled | Owner | [date] |
| R-31 | **No monitoring or alerting** of auth anomalies or outages | High | Medium | Metadata logs on stdout | Monitoring stack in backlog | Owner | [date] |
| R-32 | **Encryption at rest unconfirmed** for Instance volumes | Low | Medium | Scaleway hosting in Paris | Confirm with Scaleway **[confirm]** | Owner | [date] |
| R-33 | **No inference fallback**: a Scaleway Generative APIs outage stops all answers | Low | High | Two Scaleway models; spend-cap fallback only for external models | Owner decision Oct 21, 2026: OpenRouter routed to EU-served models with ZDR as backup; needs the CLAUDE.md entitlement rule, DPA clause 6.1, sub-processor notice and TIA changed first (`policy-business-continuity.md`) | Owner | [date] |
| R-34 | **Client-supplied file reaches another tenant** (shared tag, another tenant's workspace, de-duplication merge). *DRAFT, Oct 22, 2026* | Low | High | None needed today: no client supplies files. Existing: server-side datasets, forced RLS, out-of-package chunks dropped | Tenant-owned tags with the placement rule in API, worker and database; per-owner de-duplication; negative tests (P1b-19 step 2); clause 7A not offered before | Owner | [date] |
| R-35 | **Client lacks rights to a supplied file**: third-party claim against us for indexing, excerpts or downloads. *DRAFT* | Medium | Medium | — | Client warranty and indemnity (terms §6A); declaration per batch; withdrawal on claim (P1b-19) | Owner | [date] |
| R-36 | **Undeclared personal or special-category data in client files**. *DRAFT* | Medium | Medium | — | Declaration; reviewer check; DPA clause 7A.1; client is controller | Owner | [date] |
| R-37 | **Hostile client file** exploits the parser or plants instructions. *DRAFT* | Low | Medium | RAGFlow on internal network, no egress; no model tools | Format and size limits; untrusted wrapping of every supplied passage; supplied-file case in the guardrail eval (P1b-19 step 2); malware scan to decide (open-questions J) | Owner | [date] |

Approved by: [security lead name], for Estefania Simon-Sasyk y Otro CB, date [date].
