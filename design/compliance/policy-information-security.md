# Information Security Policy — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [Owner legal entity name], [Product name], [security contact email], [security lead name], [date]; "[confirm]" marks a fact to check |
| To finalise, the owner must | (1) name the security lead (today the owner); (2) fill in the placeholders; (3) approve and sign the approval line; (4) file it in the SOC 2 evidence set and set the review date. |

---

## 1. Purpose and scope

This policy sets the security rules for [Product name], the research assistant run by [Owner legal entity name]. It covers the platform (web app, API, workers, PostgreSQL, Redis, Authentik, RAGFlow, Caddy) on the Scaleway Instance in Paris, the code repository and CI, the people who operate it, and the vendors listed in `sub-processors.md`. The other six policies (`policy-access-control.md`, `policy-change-management.md`, `policy-incident-response.md`, `policy-vendor-management.md`, `policy-data-retention-disposal.md`, `policy-business-continuity.md`) sit under this one.

The asset we protect above all is what each client asks: questions, answers and conversation history. The second is the integrity of the corpus and its licence terms.

## 2. Rules

1. **Client isolation.** Every tenant-scoped table has `tenant_id`, a forced row-level-security policy and a `tenant_id`-first index from its first migration. Cache keys are tenant-prefixed through `app.core.cache` only.
2. **Corpus access is decided server-side.** Dataset and document IDs never come from a request.
3. **Data minimisation at the model boundary.** Prompts carry only the system prompt, the workspace's tenant-authored instructions in their delimited section, retrieved chunks with provenance, conversation turns and the question. No tenant, user or package identifier.
4. **Metadata-only logs.** No question, answer, prompt, chunk text, header or token in any log, error message or trace. Logging goes through `app.core.logging.log()` and its allow-list.
5. **Allow-listed endpoints only.** Provider hosts and model names live in `config/models.toml`, split into EU and external hosts and checked at start-up. External models only for a tenant with the operator-set entitlement, a signed acceptance and zero-data-retention routing.
6. **RAGFlow is internal.** No public listener; Caddy on 80 and 443 is the only public port.
7. **No secrets, `.env` files, real client documents or real queries in the repository.**
8. **Retention** follows `policy-data-retention-disposal.md`; chat history is never kept longer than 30 days.
9. **The model has no tools** (web search from Phase 2 only, Mistral's own tool). Crawled text is untrusted input.
10. Exceptions to this policy are written down, approved by the owner and recorded in `risk-register.md`.

## 3. Roles

| Role | Holder today |
| --- | --- |
| Security lead, platform operator, content editor and reviewer, engineering | The owner holds every internal role. There is one internal user. Separation of duties that needs two people is noted where it applies (see `risk-register.md` R-25). |
| Tenant admin | Named by each client |
| Vendors | Per `policy-vendor-management.md` |

## 4. Controls and evidence

SOC 2 criteria are indicative; confirm with the auditor.

| Control | Evidence the system already produces | Status |
| --- | --- | --- |
| Tenant isolation (CC6.1, C1.1) | `test_schema::test_table_has_forced_rls_policy_and_tenant_first_index` and `test_tenant_tables_list_is_complete` over the 18 tenant tables; `test_tenancy::test_cross_tenant_read_returns_nothing`; isolation review signed (findings §10, §12) | Built |
| Tenant-prefixed cache (C1.1) | `test_cache::test_key_carries_tenant_prefix`, `test_orchestrator::test_cache_is_not_shared_across_tenants`; static check bans `redis` imports outside `app/core/cache.py` | Built |
| No identifiers to the model (CC6.7) | `test_orchestrator::test_nothing_sent_to_mistral_identifies_tenant_user_conversation_or_package`, `test_openrouter::test_serialised_request_carries_zdr_and_no_identifiers`; tenant-name matches raise `workspace.prompt_tenant_name_match` | Built |
| Metadata-only logs (CC7.2) | `test_logging::test_log_line_contains_no_body_text`, `test_logging_policy::test_app_source_tree_follows_logging_and_cache_policy`, `test_no_bodies_in_errors` (ErrorBoundary, e0435c1) | Built |
| Endpoint allow-list and ZDR (CC6.7, CC9.2) | `test_config::test_rejects_provider_host_not_in_allow_list`, `test_model_catalogue::test_startup_rejects_an_unlisted_external_host`, `test_openrouter::test_zdr_cannot_be_overridden_by_reasoning_fields` | Built; external models off for every tenant |
| Encryption in transit (CC6.7) | Caddy TLS, Let's Encrypt certificate, HTTP → HTTPS 308 (findings §10, step 3) | Built |
| Encryption at rest (CC6.1) | Scaleway Block Storage encryption **[confirm]** | Unconfirmed |
| Secrets management (CC6.1) | `test_config::test_app_refuses_to_start_without_secrets`; secrets in env files on the Instance | Partly built; Secret Manager in backlog |
| Vulnerability scanning and pentest (CC7.1) | None | Not built (open) |
| Monitoring and alerting (CC7.2) | Structured JSON logs to stdout; no alerting | Monitoring stack in backlog |
| Security training and confidentiality terms (CC1.4) | None | Open |

## 5. Review and approval

Reviewed once a year, and on any change of vendor, hosting, model provider or data flow. Next review: [date].

Approved by: [security lead name], for [Owner legal entity name], date [date]. Security contact: [security contact email].
