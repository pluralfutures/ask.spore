# Paperwork Checklist — Before External Models Are Enabled

| | |
| --- | --- |
| Status | **DRAFT** — nothing below is done yet |
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
| 6 | GDPR roles position confirmed (processor for client user data, controller for corpus and own logs) | Owner | Open — draft assumes it | Decision recorded in the compliance guide addendum |
| 7 | Client DPA reviewed by counsel and signed by [Client], including Annex 4 (acceptance of external models, spend cap EUR 30/month) | Owner, counsel | Drafted (`client-dpa-draft.md`) | Signed copy in [document store]/clients/[Client]/; reference and date entered in the operator console (stored on the entitlement and in the audit event) |
| 8 | Sub-processor list final and given to [Client] with the DPA | Owner | Drafted (`sub-processors.md`) | `design/compliance/sub-processors.md` |
| 9 | Qwen reasoning switch confirmed with one real call on Scaleway (`reasoning_effort` `"none"` and `"medium"`, findings C26) | Engineering | Open | `design/specs/phase-1a-findings.md` (new row; usage metadata only) |
| 10 | `anthropic/claude-opus-5.5` confirmed with one real call through `eu.openrouter.ai` with the production request shape (pin, `allow_fallbacks: false`, `zdr: true`, `data_collection: "deny"`); serving provider recorded | Engineering | Open | Same; can be the same call as item 4 |
| 11 | `openai/gpt-6.1-sol` confirmed the same way | Engineering | Open | Same |
| 12 | Spend cap of EUR 30.00 (3,000 cents) set for [Client] in the operator console when enabling | Operator | Open (after 1 to 11) | Audit event `operator.entitlements_changed` |

Real calls in items 4 and 9 to 11 use a synthetic question, never a client query, and record only metadata (provider, model, token counts, status), never the prompt or answer text.

## Not required for the gate, but due before launch to the client

| Item | Owner | Status |
| --- | --- | --- |
| Trust page published (`trust-page.md`) with the outcome of item 4 | Owner | Drafted |
| Public privacy notice covering public-source personal data and our controller processing | Owner | Open |
| Second factor for tenant administrators configured in Authentik | Engineering | Open |
| Deletion wording in the DPA matched to the build (read-time expiry until the Phase 1b purge job) | Owner | Open |
