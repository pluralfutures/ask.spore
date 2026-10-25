# Staff Onboarding and Offboarding Checklist — Draft

**DRAFT for owner review, Oct 25, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 25, 2026 |
| Author | Drafted for owner review (spec item P2A-10) |
| Placeholders | [security lead name], [document store], [person], [role], [start date], [end date], [date] |
| To finalise, the owner must | (1) confirm the list of systems in §3 against what is in use; (2) name where completed checklists are filed ([document store]); (3) confirm the MFA line, which follows decision D7 of `phase-2a-build-spec.md` (TOTP for operators today, hardware keys a Phase 2 item), **proposed for the owner**; (4) approve. |

---

## 1. Purpose and scope

How a person gets, and loses, access to the platform and the accounts around it. It applies to everyone the owner gives an internal role: operator, content editor, content reviewer, security lead, and anyone with access to the Instance, the repository or a vendor console. Client users and tenant administrators are not covered; their tenant administrator manages them (`policy-access-control.md` rules 5, 6 and 8).

One completed copy per person per event (joining, changing role, leaving), signed by the security lead and filed in [document store]. While the owner is the only internal person, the checklist is used for the owner's own accounts at the first quarterly review and for the first joiner.

## 2. Rules it follows

- Least privilege (`policy-access-control.md` rule 1): grant only what the role needs, nothing "in case".
- Operators are granted and revoked only from the command line as the schema owner (`ask-spore operators grant` / `revoke`, rule 2); content roles likewise (`ask-spore content-roles`).
- Every account named below has MFA (rule 4). Operators: a second factor (TOTP) in Authentik; hardware keys or passkeys once built (Phase 2, ideas 3.4). *(Proposed for the owner, D7.)*
- Removal within 24 hours of a role ending (rule 8).
- Never share accounts or secrets; secrets are rotated when a person who held them leaves (`infra/README.md`, "Credentials rotation").

## 3. Checklist

Person: [person]. Role: [role]. Joining [start date] / leaving [end date].

| # | System | On joining | On leaving | Done (date, by) |
| --- | --- | --- | --- | --- |
| 1 | **Confidentiality and policies** | Signs the confidentiality terms; reads the information security, access control, incident response and data retention policies; records the AI-literacy training (open question G4) | Reminded in writing that confidentiality continues after leaving | |
| 2 | **Authentik account (platform sign-in)** | Account in the internal tenant with their work address; second factor enrolled and tested (TOTP; hardware key once built, D7) | Account deactivated; sessions revoked | |
| 3 | **Operator role** | Only if needed: `ask-spore operators grant`; audit event `operator.granted` checked | `ask-spore operators revoke`; `operator.revoked` checked | |
| 4 | **Content roles** | Only if needed: editor or reviewer granted from the CLI; `content_role.granted` checked | Revoked; `content_role.revoked` checked. A person named as proposer or approver in the register cannot be removed as a user (findings 1c, question 2); deactivate instead | |
| 5 | **Support access** | Briefed on `policy-access-control.md` §2.1: support reads only on a tenant administrator's grant, read only, every read shown to the tenant | Nothing to revoke (grants are to the operator role, not a person); the leaver's reads stay in the audit trail | |
| 6 | **Instance (SSH)** | Personal SSH key added to the Instance's `authorized_keys`, key fingerprint recorded; no shared key | Key removed; the Instance's `authorized_keys` checked against the record | |
| 7 | **RAGFlow UI** | Only through an SSH tunnel to the Instance's loopback (rule 10); its own account if one is needed | RAGFlow account removed; tunnel access goes with the SSH key | |
| 8 | **Repository (GitHub)** | Added to the organisation with the least role needed; MFA required by the organisation | Removed from the organisation and its teams; personal access tokens and deploy keys they created revoked | |
| 9 | **Scaleway console** | IAM user or application with the least policy needed; MFA on | IAM user or API keys removed; any key they could read rotated | |
| 10 | **Other vendor consoles** | Mistral, OpenRouter (only where external models are enabled), DNS registrar, Scaleway Transactional Email: only those the role needs, MFA on | Removed from each; keys they could read rotated | |
| 11 | **Secrets** | Told where secrets live and that they never pass through a chat or a coding session | Every secret they could read rotated per `infra/README.md` ("Credentials rotation"): database roles, `RAGFLOW_API_KEY`, Authentik tokens, provider keys | |
| 12 | **Mail and documents** | Work mailbox and [document store] access with MFA | Mailbox and document store access removed; shared documents re-owned | |
| 13 | **Devices** | Device encrypted, screen lock on, OS updates automatic | Company data removed from personal devices; company devices returned | |
| 14 | **Exit interview** | — | Exit interview held: reminded of confidentiality, asked to return or delete any copy of client or platform data, asked whether any access was missed in this list; the answer recorded here | |
| 15 | **Record** | Checklist signed by the security lead and filed | Checklist signed by the security lead within 24 hours of the role ending and filed; the next quarterly review (rule 9) confirms nothing is left | |

## 4. Review

Reviewed with the access control policy once a year, and whenever a system is added to or removed from §3.

Approved by: [security lead name], for Estefania Simon-Sasyk y Otro CB, date [date].
