# Business Continuity Policy — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [Owner legal entity name], [security lead name], [RTO], [RPO], [deputy contact], [Scaleway support plan], [document store], [date] |
| To finalise, the owner must | (1) set the recovery time and point objectives; (2) run and record the first restore test; (3) name a deputy who can act if the owner is unavailable; (4) approve and sign. |

---

## 1. Purpose and scope

How the service keeps running, or comes back, after an outage of the host, a provider, or the person who runs it. Covers the single Scaleway Instance in Paris and the services on it (Caddy, web, API, worker from Phase 1b, PostgreSQL, Redis, Authentik, RAGFlow) and the model and email providers.

## 2. What the platform is today

- **One Instance**, shared 8 vCPU, 32 GB RAM, 100 GB Block Storage, in Paris. No high availability and no second host (two-host deployment in backlog by owner decision Oct 21, 2026).
- **Backups** are run by the owner outside the build spec: nightly encrypted backup of the PostgreSQL and RAGFlow volumes to Scaleway Object Storage in Paris, object lock, 30-day retention (recommended). The restore test is pending and will be recorded in the Phase 1b findings.
- **Models**: Scaleway Generative APIs (`deepseek-v4.1-flash`, `qwen3.8-27b`). Mistral is configured but inactive. There is no automatic provider failover; the operator changes the workspace default model or the `[llm] provider` setting by hand.
- **Email**: Scaleway Transactional Email; Mailgun EU backup only after its DPA is filed.

## 3. Rules

1. **Objectives.** Recovery time objective [RTO]; recovery point objective [RPO] (with nightly backups, at most 24 hours of conversations may be lost).
2. **Restore test** at least every quarter, and after any change to the backup method. A backup that has never been restored is not counted.
3. **Rebuild from the repository.** Compose files, Caddy config, the pinned RAGFlow and Authentik versions and (from Phase 1b, P1b-08) an Authentik blueprint allow a new Instance to be built. Secrets are kept in [document store] outside the Instance so a rebuild does not depend on it.
4. **Corpus recovery.** If the RAGFlow index is lost and the backup fails, re-ingest from the manifests and the content store; this is slow (findings §9 throughput) and is the fallback, not the plan.
5. **Provider outage.** Switch to the other Scaleway model; tell tenant admins if answers change. External models fall back to the workspace default model by design.
6. **Chat history is not restored beyond its retention**: a restore must not bring back conversations already past 30 days or deleted by users; restored data is re-purged before the service reopens (from Phase 1b, P1b-14).
7. **Clients are told** of an outage longer than [RTO] through their tenant admin contact.
8. **Key person.** The owner is the only operator. A sealed access procedure for [deputy contact] is kept in [document store].

## 4. Roles

The owner holds every role. [deputy contact] is the fallback for account access only, not for operating the platform.

## 5. Controls and evidence

| Control | Evidence the system already produces | Status |
| --- | --- | --- |
| Backups (A1.2) | Object Storage bucket with object lock | Owner-run; not verified in this repository |
| Restore test (A1.3) | Phase 1b findings entry | Pending |
| Reproducible infrastructure (A1.2) | `infra/compose.dev.yml`, `infra/caddy/`, `infra/ragflow/VERSION`, `infra/authentik/README.md` | Built; blueprint from P1b-08 |
| Spend-cap fallback to an EU model | `model.fallback` audit event | Built |
| Health check | `GET /healthz` returns 200 (findings §10, step 3) | Built; no external uptime monitor |
| Monitoring and alerting | — | Backlog |
| Provider failover | Manual configuration change | Manual |

## 6. Review and approval

Reviewed once a year and after every major outage. Next review: [date].

Approved by: [security lead name], for [Owner legal entity name], date [date]. Scaleway support: [Scaleway support plan].
