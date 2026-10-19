# Phase 1a Findings

Status: started with Group A (P1a-01 to P1a-03), Oct 19, 2026. P1a-16 adds the signed
isolation-test review to this file.

## 1. Where the Group A build differs from the spec

Recorded as built, per `CLAUDE.md` ("when the design and the code must diverge, update the
design document").

| # | Item | Spec says | What we did and why |
| --- | --- | --- | --- |
| A1 | P1a-01 | `users.status` (values not given) | `invited`, `active`, `deactivated`. `invited` is a user created by an operator or admin who has not signed in yet; the first successful sign-in makes them `active` (P1a-02). Only `active` users of `active` tenants pass authentication. |
| A2 | P1a-01 | `tenants.status` (values not given) | `active`, `suspended`. Termination and its purge cascade (architecture §7.4) are not in Phase 1a. |
| A3 | P1a-01 | `tenant_entitlements(tenant_id, answer_modes[], …)` | Also `updated_at`. `answer_modes` is checked against the Phase 1a modes (`corpus_only`, `general_knowledge`) and must contain `corpus_only`; web search (Phase 2) widens the check in its own migration. |
| A4 | P1a-01 | "Phase 0's hard-coded tenant becomes a row" | It was already a row (revision 0001 seeded `internal`). What was hard-coded was the request context: the Phase 0 middleware set `INTERNAL_TENANT_ID` itself. Now both auth modes resolve the context from the user's row, looked up inside the tenant the credential names (`app.tenancy.context.resolve_user`), and a route without a context returns 401 before opening a transaction. The Phase 0 bearer token still admits only active users of the internal tenant. |
| A5 | P1a-01 | (stub) | **Stub until P1a-04.** The package is still Phase 0's (every tag in `config/tags.toml`), and only the internal tenant gets it (`app.chat.package.tenant_package_tags`). A client tenant created by the operator before its workspaces exist retrieves nothing and abstains, rather than inheriting our corpus. P1a-04 replaces the stub with the workspace's tags. |
