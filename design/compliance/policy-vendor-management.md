# Vendor Management Policy — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [security lead name], [document store], [date] |
| To finalise, the owner must | (1) file the vendor documents listed in `paperwork-checklist.md` items 1 to 3 and 13; (2) collect Scaleway's SOC 2 or ISO 27001 evidence; (3) approve and sign. |

---

## 1. Purpose and scope

How we choose, contract, monitor and leave vendors that process platform data, and how we keep the content-licence inventory. The maintained list is `sub-processors.md`.

## 2. Rules

1. **No vendor receives client data before** its DPA is accepted and filed, and, for a non-EU transfer, the SCCs and a transfer impact assessment are on file.
2. **Model providers** need a written zero-data-retention confirmation naming our organisation, models and endpoints, and how provider-side prompt caching is treated. Model versions are pinned; terms are re-checked before any model change.
3. **Every outbound host is on the allow-list** in `config/models.toml`; a vendor not on it cannot be reached.
4. **External models** (OpenRouter EU endpoint, upstream Amazon Bedrock and Microsoft Azure) only for a tenant with the entitlement, the client's signed acceptance and ZDR routing; off for every tenant today.
5. **Exactly one email provider is active**: Scaleway Transactional Email (fr-par). Mailgun EU is a backup, not active, and needs its DPA filed before it is switched on.
6. **Clients get 30 days' notice** of a new or replacement sub-processor (client DPA clause 5.2), except where an urgent replacement is needed for security or continuity, when we notify as soon as possible and the objection right still applies.
7. **Annual review** of each vendor: DPA version, security report, region, retention terms, ZDR status, the upstream list for OpenRouter. Recorded in `sub-processors.md` change log.
8. **Content licences** are vendor terms too: each source carries a licence basis in the source register; downloads only for sources flagged `downloadable`.
9. **Exit.** When a vendor is removed, request deletion and confirmation, remove the host from the allow-list and rotate keys.

## 3. Roles

The owner holds the security lead role and signs vendor contracts. Counsel reviews DPAs with SCCs.

## 4. Controls and evidence

| Control | Evidence the system already produces | Status |
| --- | --- | --- |
| Allow-list with EU and external split (CC9.2) | `test_config::test_rejects_provider_host_not_in_allow_list`, `test_model_catalogue::test_startup_rejects_an_eu_service_on_an_external_host` | Built |
| ZDR and data collection denied on every external request (CC9.2, C1.2) | `test_openrouter::test_pinned_model_request_carries_the_pin_zdr_and_no_identifiers`, `test_zdr_cannot_be_overridden_by_reasoning_fields` | Built |
| External only with entitlement and acceptance (CC9.2) | `test_operator::test_database_refuses_external_models_without_acceptance`; `operator.entitlements_changed` with acceptance reference | Built; never enabled |
| Spend cap and fallback (CC9.2) | `usage_ledger`; `model.fallback` audit event; `test_spend_cap::*` | Built |
| Sub-processor inventory (CC9.2) | `sub-processors.md` | Drafted |
| Scaleway DPA filed | — | Entered into (version of June 1, 2024); filing to record (checklist item 2) |
| Scaleway zero-retention evidence | Published policy, version of Oct 3, 2025 (Scaleway issues no letter) | Accepted by owner Oct 26, 2026 (findings M2, checklist item 3) |
| OpenRouter DPA with SCCs, TIA | `transfer-impact-assessment.md` | Drafted; DPA signed Oct 23, 2026, SCC details and filing to record (items 1, 4, 5) |
| Vendor security reports on file | — | Open |
| Content-licence inventory | `sources` table (licence basis, `downloadable`); licence files from Phase 1b (P1b-01 `licence_file_path`) | Partly built |

## 5. Review and approval

Reviewed once a year. Next review: [date].

Approved by: [security lead name], for Estefania Simon-Sasyk y Otro CB, date [date].
