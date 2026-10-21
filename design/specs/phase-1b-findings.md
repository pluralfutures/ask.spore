# Phase 1b Findings

Build notes for `phase-1b-build-spec.md`, kept like `phase-1a-findings.md`: where a build
differs from the spec, and why. Metadata only: no query, answer, token, link or email
address is recorded here.

## 1. Where the Group A build differs from the spec

Group A (content operations, P1b-01 to P1b-05) records its rows here.

## 2. Where the Group B build differs from the spec

Group B: client SSO connectors and sign-in hardening, P1b-06 to P1b-08, on branch
`phase-1b/group-b`. Migrations are numbered 0020 onwards on 0012, because Group A1 adds
0013 onwards at the same time; the integration step re-parents 0020 onto Group A1's last
revision (one `down_revision` line).

| # | Item | Spec says | Built |
| --- | --- | --- | --- |
| B1 | P1b-06 | `tenant_login_policy(tenant_id, sign_in_links_enabled, sso_source_kind, sso_source_config, jit_provisioning_enabled, admin_mfa_required)` | As listed, plus `sso_source_slug` (the Authentik source's slug, unique, set exactly when a kind is) and `updated_at` (revision 0020). Forced RLS, `tenant_isolation`, primary key `tenant_id`. The operator role reads, inserts and updates; the pre-authentication role reads the columns discovery needs; the application role reads its own tenant's row and cannot write it. A trigger on `tenants` gives every new tenant its row, so sign-in code requires the row and fails closed without it. `sign_in_links_enabled` is copied from `tenant_entitlements` and the old column dropped; the downgrade moves it back (tested both ways). The operator's switches moved from `PUT …/entitlements` to `PUT /api/v1/operator/tenants/{id}/login-policy`. |
| B2 | P1b-06 | "an unknown domain gets the same neutral response as an unknown user" | Discovery is its own public route, `POST /api/v1/auth/discover`, and is domain-level only: it never reads users, so every address of a domain gets the same answer. The neutral answer (`methods: ["sign_in_link"]`) goes to an unknown domain, a malformed address, a suspended tenant's domain, a domain claimed by two tenants (refused by the console, possible only as the owner) and **a tenant with links off and no SSO**: offering it nothing would tell the caller that the domain is a client's. Its link request is then refused without saying why, as before. A tenant with SSO is necessarily recognisable by its domain; that is what discovery is for (architecture §4.3). |
| B3 | P1b-06 | "the domain resolves to the tenant … and to that tenant's allowed methods" | Discovery decides what the page offers; sending a link still goes by the user, as in P1a-02: a link goes to an invited or active user of an active tenant whose policy has links on, whatever their address's domain (an invited address outside the verified domains, such as the first admin of `cc`, still signs in with links). |
