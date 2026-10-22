# Client Offboarding Pack — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [Client], [Client legal name], [support email], [privacy contact email], [security contact email], [termination date], [notice date], [export window days], [backup retention days], [certificate number], [signatory name], [signatory title], [recipient first name], [admin name], [Services Agreement], [export format], [secure transfer method], [n] (counts), [date] |
| To finalise, the owner must | (1) fill in the placeholders; set [export window days] (proposed 30) and [backup retention days] (30, matching the owner-run backup retention) and check both against `terms-of-service.md` and DPA clause 10.5; (2) decide the manual export format (section 1, step 3) until an export tool exists; (3) until P1b-14 passes its tests, use the manual purge in section 1.4 and the "manual" wording of the certificate; (4) decide how the 12-month audit retention is ended for a terminated tenant, since the audit table refuses deletion by design (open question); (5) have counsel check the certificate wording and the exit emails against the DPA. |

---

## 1. Termination and deletion procedure

Applies when [Client]'s agreement ends, by expiry or by notice. Roles: the **operator** runs the steps; the **owner** signs the certificate. Every step that changes data is audited.

### 1.1 Timeline

| When | Step |
| --- | --- |
| Notice received ([notice date]) | Confirm termination and the dates in writing (email 3.2). Agree the [termination date] |
| From notice to [termination date] | Service continues. Export window: the client may ask for an export up to [export window days] days before the [termination date] |
| [termination date] | Suspend the tenant (1.3) |
| Within [30] days of the [termination date] | Purge (1.4), certificate (section 2), email 3.4 |
| Within [backup retention days] days after the purge | Backups containing the tenant's data age out |
| 12 months after each audit event | Audit events reach the end of their retention (DPA clause 10.4) |

### 1.2 Export

Conversations are never more than 30 days old (fewer if the client shortened retention), so there is little to export. There is **no self-service or automated export** in SporeBot today; conversation export is not built. On request, the operator produces an export of the tenant's user list (email, name, role, status, last sign-in) and current conversations (questions, answers, citations) in [export format, for example JSON or Markdown] as a manual, audited step, and delivers it to the client's named administrator by [secure transfer method]. Nothing exported is kept by us after delivery. Send email 3.3 when it is ready.

### 1.3 Suspension

1. Switch off the external-models entitlement if it is on (operator console; audited `operator.entitlements_changed`).
2. Set the tenant's status to `suspended`. Every request for a suspended tenant is refused, and no sign-in link is sent. There is no console button for this yet: the schema owner sets it from the command line, and the operator records the change [owner: add an audited CLI command or console action; until then note the change in the paperwork checklist].
3. Switch sign-in links off for the tenant (from Phase 1b, P1b-06), and disable the tenant's SSO source in Authentik (from Phase 1b, P1b-07).

### 1.4 Purge

**From Phase 1b (P1b-14):** the per-tenant termination purge deletes the tenant's conversations, messages, citations, feedback, downloads records, sign-in link records, tenant settings, workspaces and users, clears the tenant's answer-cache keys (all keys under the tenant's prefix), and writes the figures for the certificate (section 2). The tenant's Authentik users are removed by the operator in Authentik's admin interface as a separate, audited step (not part of P1b-14). It is tested: after the purge no row for the tenant remains outside the audit log.

**Until P1b-14 is live:** the operator runs the same deletions by hand as the schema owner, in one transaction per table group, following a written script [owner: attach the script], records the row counts before and after, deletes the Authentik users through Authentik's admin interface, and clears the cache keys under the tenant prefix through `app.core.cache` tooling. The certificate then says "manual procedure".

**What is kept:**

- **Audit events** of the tenant's users (sign-ins, admin actions, query and download metadata; never question or answer text) for the rest of their 12-month retention, to evidence security and compliance (DPA clauses 10.4 and 10.5). They name user IDs, not email addresses.
- **Backups** that were taken before the purge, until they age out after [backup retention days] days. They are encrypted and not restored except for disaster recovery; if one is ever restored, the purge is re-run before the service resumes.
- **Usage and spend figures** in aggregated form, and our contract and billing records, as required by law.
- **Nothing in the corpus**: the client uploaded no documents, so there is no corpus content to return or delete. *DRAFT, Oct 22, 2026 (P1b-19, architecture §15.8):* for a client that supplied documents under the terms §6A, the purge first withdraws every source the client supplied (RAGFlow file, parsed text, chunks and embeddings in every dataset), deletes the datasets of the client's own tags, deletes the files and declarations under the client's content-store directory, and erases the descriptive fields of the register rows (title, publisher, canonical link, hash), keeping an ID, the tenant ID and the withdrawal date and reason. Copies are returned on request before the end date (terms §13.3). Declarations we keep as contract evidence are kept for 5 years after the contract ends and listed under contract records.

Model providers hold nothing to delete: prompts are processed under zero-retention terms.

### 1.5 After the purge

1. Issue the certificate (section 2) to the client's named contact; send email 3.4.
2. Remove the tenant's verified domains so they can be registered again.
3. Update `paperwork-checklist.md` (client row: terminated, certificate number, date).

---

## 2. Certificate of deletion — template

> **Certificate of Deletion** · No. [certificate number]
>
> Estefania Simon-Sasyk y Otro CB ("Provider") confirms to **[Client legal name]** ("Client") that, following the end of the [Services Agreement] on [termination date], it has deleted the Client Personal Data it processed in SporeBot, as required by clause 10.5 of the Data Processing Agreement.
>
> | | |
> | --- | --- |
> | Date of deletion | [date] |
> | Method | [Automated termination purge (P1b-14) / Manual procedure, documented and audited] |
> | User accounts deleted (application and identity service) | [n] |
> | Conversations deleted | [n] |
> | Messages deleted | [n] |
> | Feedback entries deleted | [n] |
> | Download records deleted | [n] |
> | Workspaces and settings deleted | [n] |
> | Cached answers removed | All entries under the Client's cache prefix |
> | Client-supplied documents deleted (file, text, index) *[only if the Client supplied documents; DRAFT, Oct 22, 2026]* | [n] |
> | Client-owned content collections deleted *[same]* | [n] |
> | Stored copies of client-supplied documents removed *[same]* | [n] |
>
> **Retained, and until when:**
>
> - Audit records of the Client's users (sign-in, administrative, query and download metadata; no question or answer text): until 12 months after each record was created, the last on [date].
> - Encrypted backups made before the deletion date: until [date] ([backup retention days] days), after which they are overwritten.
> - Contract and billing records: as required by law.
>
> [The Client uploaded no documents to the Service, so no document content was held. / The documents the Client supplied are deleted as counted above, and the copies returned on [date] if requested.] Language-model providers processed requests under zero-data-retention terms and hold no Client data.
>
> Signed for Estefania Simon-Sasyk y Otro CB: [signatory name], [signatory title], [date]

The counts are the figures written by the P1b-14 purge (or recorded by hand under the manual procedure). They are counts only; the certificate lists no names or addresses.

---

## 3. Notices and exit emails

Same rules as the onboarding templates (`onboarding-pack.md` section 2): sent over Scaleway Transactional Email (fr-par) with tracking off; only the recipient's own details; no question, answer or document. The platform sends mail from Phase 1b (P1b-11); until then these are sent by the owner from [support email].

### 3.1 User deactivation notice (to a user deactivated by their administrator)

Sent by the tenant administrator, or by the platform from Phase 1b (P1b-11). Deactivation is already built: the tenant administrator deactivates a user on the admin page, the user's next request is refused, and the change is audited.

Subject: Your SporeBot access has ended

> Hello [recipient first name],
>
> Your organisation's administrator has ended your access to SporeBot. You can no longer sign in.
>
> Your conversations are no longer available to you. They are removed when your organisation's retention period ends, at most 30 days after each conversation started. A record that you used the service (sign-ins and similar events, without the content of your questions) is kept for 12 months for security reasons.
>
> If you think this is a mistake, contact your administrator, [admin name]. For questions about your data: [privacy contact email].
>
> SporeBot · Estefania Simon-Sasyk y Otro CB

### 3.2 Termination confirmation (to the client's administrator)

Subject: Confirmation: SporeBot service for [Client] ends on [termination date]

> Hello [recipient first name],
>
> We confirm that [Client]'s use of SporeBot ends on [termination date].
>
> - Until then the service works as usual.
> - If you would like an export of your user list and current conversations, ask us by [date] ([export window days] days before the end date). Conversations are at most 30 days old, so an export holds only recent material.
> - On [termination date] we suspend access. Within 30 days we delete your users, conversations and settings and send you a certificate of deletion.
>
> Contact: [support email]
>
> SporeBot · Estefania Simon-Sasyk y Otro CB

### 3.3 Export ready

Subject: Your SporeBot export is ready

> Hello [recipient first name],
>
> The export you asked for is ready. It contains [your user list and current conversations] as of [date]. We will send it by [secure transfer method]; it will not be sent as an email attachment. We do not keep a copy after delivery.
>
> SporeBot · Estefania Simon-Sasyk y Otro CB

### 3.4 Deletion complete

Subject: SporeBot: deletion of [Client]'s data is complete

> Hello [recipient first name],
>
> We have deleted [Client]'s users, conversations and settings from SporeBot. Your certificate of deletion (No. [certificate number]) is attached.
>
> As the certificate states, audit records without question or answer text are kept until 12 months after each was created, and encrypted backups made before the deletion are overwritten by [date].
>
> Thank you for using SporeBot.
>
> SporeBot · Estefania Simon-Sasyk y Otro CB · [privacy contact email]

---

## 4. Staff and operator offboarding checklist

For anyone at Estefania Simon-Sasyk y Otro CB who leaves or no longer needs access. Complete within **24 hours** of the departure or role change (`policy-access-control.md`).

| # | Step | Evidence |
| --- | --- | --- |
| 1 | Revoke the operator role: `ask-spore operators revoke --email …` (run as the schema owner) | Audit event `operator.revoked` under the internal tenant |
| 2 | Remove content roles (from Phase 1b, P1b-01) | Audit event |
| 3 | Disable the person's Authentik user and remove their MFA devices; end their sessions | Authentik event log |
| 4 | Remove SSH keys from the Instance and the person from the Scaleway project (IAM) | Scaleway audit trail |
| 5 | Remove access to GitHub, the document store and any provider console (Scaleway, OpenRouter, Mailgun) | Provider logs |
| 6 | Rotate every secret the person could read: provider API keys, the RAGFlow service key, the Transactional Email credential, database credentials, the Authentik API token and client secret. Secrets are in environment files on the Instance until Secret Manager (backlog) | Date of rotation in the paperwork checklist |
| 7 | Return or wipe company devices | Signed note |
| 8 | Record completion with date and time | Access-review log |
