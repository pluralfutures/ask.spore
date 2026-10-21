# Access Control Policy — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [Owner legal entity name], [security lead name], [document store], [date] |
| To finalise, the owner must | (1) confirm that operator accounts use hardware-key MFA in Authentik and record the check; (2) set the dates of the first quarterly access review; (3) approve and sign. |

---

## 1. Purpose and scope

Who may reach what on the platform, how access is granted and removed, and how it is checked. Covers client users and tenant admins, platform operators, content roles, the Scaleway console, the Instance (SSH), Authentik, RAGFlow's UI, GitHub and vendor accounts.

## 2. Rules

1. **Least privilege.** Client roles are `user` and `tenant_admin`, scoped to one tenant. Operators work on the internal tenant and run as the database role `askspore_operator`, which cannot read conversations, messages, citations, feedback, sign-in links or the private corpus columns (findings A12).
2. **Operators are granted only from the command line** as the schema owner (`ask-spore operators grant` / `revoke`), never from the web app.
3. **Sign-in.** Users sign in with a single-use emailed link (15 minutes, consumed only by a POST from the landing page, bound to the requesting browser, at most 5 links per user per window, no account enumeration). Client SSO (Entra ID, Google Workspace, generic OIDC, SAML) from Phase 1b (P1b-07).
4. **MFA.** Operators: hardware-key MFA configured in Authentik. Tenant admins: second factor enforced from Phase 1b (P1b-08). Scaleway, GitHub and vendor consoles: MFA on every account.
5. **A user of one tenant can never act in another.** Tenant binding comes from the Authentik attribute set at provisioning, never from a claim or a request.
6. **Invitations** only for addresses on the tenant's verified domains; an address already in any tenant is refused.
7. **No support impersonation.** Time-boxed, logged support access is planned (architecture §7.4) and not built; until then operators do not view tenant content at all.
8. **Removal.** Internal access is removed within 24 hours of a role ending; client users are deactivated by their tenant admin or, on request, by the operator.
9. **Review.** Every quarter the security lead reviews operators, Authentik admins, Scaleway IAM, SSH keys and GitHub collaborators, and records the result.
10. **Infrastructure.** SSH by key only; RAGFlow's UI is reachable only on the Instance's loopback (via an SSH tunnel).

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
| Operator hardware-key MFA (CC6.1) | Authentik configuration; not checked by the API (A12) | To verify |
| Per-IP rate limit on link requests | — | From Phase 1b (P1b-08) |
| Session revocation on sign-out | `auth.signed_out`; `revoked_sessions` table; live check of the Authentik revocation from Phase 1b (P1b-08) | Partly built |
| Quarterly access review (CC6.2) | Sign-off record in [document store] | Not started |
| Time-boxed support access (CC6.3) | — | Not built (open) |

## 5. Review and approval

Reviewed once a year and whenever a role, identity provider or login method changes. Next review: [date].

Approved by: [security lead name], for [Owner legal entity name], date [date].
