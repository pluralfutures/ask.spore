# Access Control Policy — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Revision | Oct 25, 2026, **DRAFT** (spec item P2A-10): rule 7 replaced by the support-access policy (§2.1), built in P2A-08; the operator MFA line of rule 4 changed to TOTP (decision D7 of `phase-2a-build-spec.md`, **taken by the owner Oct 25, 2026**); staff onboarding and offboarding in `staff-access-checklist.md` |
| Placeholders | [security lead name], [document store], [date], [first review date] |
| To finalise, the owner must | (1) record that every operator account has TOTP configured in Authentik (D7 taken Oct 25, 2026); (2) set the date of the first quarterly access review (open question H2) in §2 rule 9; (3) approve and sign. |

---

## 1. Purpose and scope

Who may reach what on the platform, how access is granted and removed, and how it is checked. Covers client users and tenant admins, platform operators, content roles, the Scaleway console, the Instance (SSH), Authentik, RAGFlow's UI, GitHub and vendor accounts.

## 2. Rules

1. **Least privilege.** Client roles are `user` and `tenant_admin`, scoped to one tenant. Operators work on the internal tenant and run as the database role `askspore_operator`, which cannot read conversations, messages, citations, feedback, sign-in links or the private corpus columns (findings A12).
2. **Operators are granted only from the command line** as the schema owner (`ask-spore operators grant` / `revoke`), never from the web app.
3. **Sign-in.** Users sign in with a single-use emailed link (15 minutes, consumed only by a POST from the landing page, bound to the requesting browser, at most 5 links per user per window, no account enumeration). Client SSO (Entra ID, Google Workspace, generic OIDC, SAML) from Phase 1b (P1b-07).
4. **MFA.** Operators: a time-based one-time code (TOTP) as second factor, configured in Authentik; hardware keys or passkeys are a Phase 2 item (ideas 3.4) and are not required until built. *(Decision D7 of `phase-2a-build-spec.md`, taken Oct 25, 2026; the API does not check the factor, findings A12.)* Tenant admins: second factor enforced from Phase 1b (P1b-08). Scaleway, GitHub and vendor consoles: MFA on every account.
5. **A user of one tenant can never act in another.** Tenant binding comes from the Authentik attribute set at provisioning, never from a claim or a request.
6. **Invitations** only for addresses on the tenant's verified domains; an address already in any tenant is refused.
7. **Support access only on the tenant's grant, never by impersonation.** Operators do not read a tenant's conversations or settings unless one of the tenant's administrators grants time-boxed access, under the policy in §2.1 (built in Phase 2A, P2A-08).
8. **Removal.** Internal access is removed within 24 hours of a role ending; client users are deactivated by their tenant admin or, on request, by the operator.
9. **Review.** Every quarter the security lead reviews operators, Authentik admins, Scaleway IAM, SSH keys and GitHub collaborators, and records the result. The review also lists the support grants read in the quarter (`operator.support_viewed` events across tenants) and checks each against the tenant's request. First review: [first review date] (set by the owner, open question H2). Joiners and leavers follow `staff-access-checklist.md`.
10. **Infrastructure.** SSH by key only; RAGFlow's UI is reachable only on the Instance's loopback (via an SSH tunnel).

### 2.1 Support access

What the consent notice (v1 §1 and §7), the client DPA (clause 3.2) and the privacy notice (§2) promise, and how the system enforces it (P2A-08; architecture §7.4).

1. **Who requests it.** Only a tenant administrator of the client, from the "Support access" section of their administration page. Operators do not ask for a grant through the product; when an operator needs to look at something to answer a support request, they tell the client's contact what to grant, and the administrator decides.
2. **What may be granted.** One scope per grant: the tenant's **settings** (chat-history retention, each workspace's defaults and current additional instructions), or **one conversation**, chosen from the administrator's own conversation list. An administrator cannot grant another user's conversation; a user who wants support on their own conversation asks the operator through their administrator, who cannot share it either, so that conversation stays unread. Every grant carries a note saying what to look at.
3. **How long.** From 15 minutes to 4 hours; 1 hour by default. The end time is fixed when the grant is made and cannot be extended; a longer need is a new grant. The administrator can revoke a grant at any time, and the next read is refused.
4. **Who may hold one.** The grant is to the platform operators (the people granted the operator role under rule 2), not to a named person. Each read names the operator who made it. Content roles (editor, reviewer) and anyone else have no access through a grant.
5. **What the operator can do.** Read the granted scope as the user sees it, in a read-only view, under their own operator session and identity. No impersonation, no writing, no other conversation, no other tenant. The database enforces the same: reads run as the role `askspore_support`, whose policies show a conversation only while an open grant names it and the settings only while an open settings grant exists (revision 0065).
6. **How it is checked.** On every read: the grant must belong to the tenant named, be of the scope read, name the conversation read, and be neither revoked nor expired. Anything else is answered as not found, so a refusal reveals nothing. The daily purge job also closes expired grants.
7. **How the tenant sees it.** The administration page lists every grant with its state (open, viewed, expired, revoked), how many times the operators read it and when last. Each grant, revocation and read is an audit event under the tenant (`tenant_admin.support_granted`, `tenant_admin.support_revoked`, `operator.support_viewed`, `support.grant_expired`) and is in the tenant's audit-log download. No content is ever written to a log or an audit event: identifiers and codes only.
8. **Review.** The quarterly review (rule 9) lists the reads of the quarter and checks each against a request from the tenant.

## 3. Roles

The owner holds the operator, content editor, content reviewer and security lead roles. With one internal user, self-approval of sources is allowed and audited until a second internal user exists (P1b-01). The quarterly review is a self-review until then; see `risk-register.md` R-25.

## 4. Controls and evidence

| Control | Evidence the system already produces | Status |
| --- | --- | --- |
| Sign-in events (CC6.1) | Audit events `auth.login` (with method), `auth.signed_out`, `auth.link_refused` (`rate_limited`) | Built |
| Link hardening (CC6.1) | `link_ttl_seconds = 900`, `links_per_window = 5` in `config/models.toml`; database constraint `expiry_cap` (15 minutes) | Built |
| Token per tenant (CC6.1) | `test_auth::test_token_for_tenant_a_cannot_act_on_tenant_b`, `test_phase0_auth::test_user_of_another_tenant_is_rejected` | Built |
| Operator separation (CC6.3) | `operator.granted`, `operator.revoked` events under the internal tenant; revision 0006 privileges, tested | Built |
| Tenant admin actions (CC6.2) | `tenant_admin.user_invited`, `tenant_admin.user_changed`, `tenant_admin.retention_changed`, `tenant_admin.workspace_defaults_changed`; `test_tenant_admin::test_admin_cannot_change_self_or_another_tenants_user` | Built |
| Invite scope (CC6.2) | `test_operator::test_invite_refuses_an_email_of_another_tenant`; findings D6 | Built |
| Client SSO and JIT by verified domain (CC6.1) | — | From Phase 1b (P1b-06, P1b-07) |
| Admin MFA (CC6.1) | — | From Phase 1b (P1b-08) |
| Operator second factor (CC6.1) | Authentik configuration (TOTP, D7 taken Oct 25, 2026; hardware keys Phase 2); not checked by the API (A12) | To verify |
| Per-IP rate limit on link requests | — | From Phase 1b (P1b-08) |
| Session revocation on sign-out | `auth.signed_out`; `revoked_sessions` table; live check of the Authentik revocation from Phase 1b (P1b-08) | Partly built |
| Quarterly access review (CC6.2) | Sign-off record in [document store]; first review [first review date] | Not started |
| Staff joiners and leavers (CC6.2, CC6.3) | Completed `staff-access-checklist.md` per person, filed in [document store] | Not started (no second person yet) |
| Time-boxed support access (CC6.3) | `support_grants` (revision 0065); audit events `tenant_admin.support_granted`, `tenant_admin.support_revoked`, `operator.support_viewed`, `support.grant_expired`; the tenant's administration page and audit download; `tests/test_support_access.py` (no grant, expired, revoked, other conversation and other tenant refused; database policies; no content in logs) | Built (P2A-08); live check at the Phase 2A release (P2A-14) |

## 5. Review and approval

Reviewed once a year and whenever a role, identity provider or login method changes. Next review: [date].

Approved by: [security lead name], for Estefania Simon-Sasyk y Otro CB, date [date].
