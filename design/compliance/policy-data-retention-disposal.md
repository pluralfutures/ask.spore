# Data Retention and Disposal Policy — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [security lead name], [document store], [log rotation period], [period] (licence files after a source is removed; usage ledger), [date]; "[confirm]" marks a fact to check |
| To finalise, the owner must | (1) decide the disposal procedure for audit events older than 12 months (§4); (2) confirm the Docker log rotation setting on the Instance; (3) confirm the backup retention once backups run; (4) approve and sign. |

---

## 1. Purpose and scope

How long each kind of data is kept and how it is disposed of. Covers the platform database, Redis, the content store, RAGFlow, logs, backups, the repository and vendors. Client-facing commitments are in the client DPA (clause 10) and `offboarding-pack.md`.

## 2. Rules

1. **Chat history is never kept longer than 30 days.** No setting may allow more. Tenant admins may shorten it.
2. **Keep only what the schedule lists**, for no longer than it says.
3. **Disposal is deletion**, not hiding, once the purge job runs (from Phase 1b, P1b-14). Until then the 30-day limit is applied at read time: expired conversations are unreachable through every route, but rows remain in the database.
4. **Backups** expire on their own schedule; a deleted row may survive in a backup until that backup expires.
5. **On termination** the client's history and account data are deleted per `offboarding-pack.md`, with a certificate of deletion (from Phase 1b, P1b-14).
6. **No real queries in the repository**; eval results are committed as metrics only.

## 3. Retention schedule

| Data | Where | Retention | How disposed | Status |
| --- | --- | --- | --- | --- |
| Conversations, messages, citations, feedback | PostgreSQL | Tenant setting, 1 to 30 days (default 30); 0 ("no history") from Phase 1b | Read-time expiry on `expires_at` today; purge job deletes rows from Phase 1b (P1b-14); user delete is a hard delete at once (`conversation.deleted`) | Read-time built; purge from P1b-14 |
| Answer cache | Redis | `cache_ttl_seconds = 86400` (1 day); capped at 30 days in code | Redis expiry | Built |
| Sign-in links | PostgreSQL | Valid at most 15 minutes (`expiry_cap`); rows kept until purged | Purge of expired rows **[not in P1b-14 as written; confirm]** | Open |
| Revoked sessions | PostgreSQL `revoked_sessions` | Until the token's expiry (8 hours) | Purge job from Phase 1b (P1b-14) | From P1b-14 |
| Download records | PostgreSQL `downloads` | 90 days (owner decision Oct 21, 2026) | Purge job from Phase 1b (P1b-14); the `download` audit event stays | From P1b-14 |
| Accounts | PostgreSQL, Authentik | Term of the client agreement; deactivated users kept as records | Termination purge from Phase 1b (P1b-14) | From P1b-14 |
| Audit events | PostgreSQL `audit_events`, append-only | 12 months | **No disposal path today**: a trigger rejects UPDATE and DELETE for every role, including the owner. See §4 | Open |
| Application logs | Container stdout on the Instance (metadata only) | [log rotation period] **[confirm Docker log rotation]** | Rotation | To confirm |
| Backups of PostgreSQL and RAGFlow volumes | Scaleway Object Storage, Paris (owner-run) | 30 days, object lock (recommended) | Expiry | Owner-run; restore test pending |
| Corpus: source register, parsed chunks, embeddings | PostgreSQL `sources`, RAGFlow | While licensed and relevant; removed on takedown | Withdrawal from every dataset and the cache from Phase 1b (P1b-03); manual until then | From P1b-03 |
| Content store (file copies for downloads) | Instance volume `content_root` | Same as the source | Deleted with the source | Manual until P1b-03 |
| Licence and permission files | `content_root` from Phase 1b (P1b-01), never in RAGFlow | While the source is held, plus [period] for disputes | Manual | From P1b-01 |
| Crawl snapshots (raw HTML, fetch date) | `content_root` | Same as the page | With the page | From P1b-04 |
| Eval results | Repository `packages/eval/results/` | Indefinite, metrics and verdicts only, no answer text | — | Built (owner decision Oct 21, 2026) |
| Usage ledger (tokens, cost per tenant) | PostgreSQL | [period] | [confirm] | Open |
| Model providers | Scaleway, OpenRouter and upstream | Zero retention, except where required by law or to investigate abuse | Vendor terms | Scaleway letter pending (M2) |
| Email delivery logs | Scaleway Transactional Email | Per Scaleway's documentation **[confirm]** | Vendor | To confirm |

## 4. Audit events past 12 months

The audit table is write-once by design. The owner must choose one of: (a) a dated, audited procedure run as the schema owner that disables the trigger in a single transaction, deletes rows older than 12 months and re-enables it; (b) monthly partitions, dropping whole partitions older than 12 months; (c) keep events longer and state a different period in the DPA. Until decided, events are kept (`risk-register.md` R-28).

## 5. Controls and evidence

| Control | Evidence the system already produces | Status |
| --- | --- | --- |
| 30-day cap (CC6.5, Art. 5(1)(e)) | `test_schema::test_conversation_retention_capped_at_30_days`, `test_tenant_admin::test_retention_cannot_be_set_above_30_days`, database constraint `retention_cap` | Built |
| Read-time expiry on every route | `test_api::test_conversation_older_than_30_days_is_not_returned_by_any_read_route` | Built |
| Retention changes audited | `tenant_admin.retention_changed`; `test_retention_of_one_tenant_does_not_touch_another` | Built |
| Purge and certificate | — | From Phase 1b (P1b-14) |
| Withdrawal cascade | — | From Phase 1b (P1b-03) |

## 6. Review and approval

Reviewed once a year. Next review: [date].

Approved by: [security lead name], for Estefania Simon-Sasyk y Otro CB, date [date].
