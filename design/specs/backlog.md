# Backlog

Ideas and deferred items raised during a phase that belong to a later phase. One line each, with the phase it belongs to.

- Phase 1: pin container images by digest, not only by tag (architecture §8 "Hardening"); Phase 0 pins exact tags. Raised in P0-02.
- ~~Phase 1: write auth events (success, failure with method) to `audit_events` once Authentik replaces the Phase 0 bearer token; P0-06 only logs rejections. Raised in P0-06.~~ Done in P1a-02 (`auth.login`, `auth.login_failed`, `auth.link_requested`, `auth.link_refused`, each with `method`).
- Phase 1: decide the production path for the RAGFlow web UI, whose nginx also proxies RAGFlow's API (findings R3): keep it on the Private Network only, or front it with an authenticating proxy. Raised in P0-02.
- Phase 1: replace the 4-characters-per-token estimate (history and context caps) with Mistral's tokenizer. Raised in P0-14.
- Phase 1: keep the question (and a partial answer, flagged) when the model fails or the client disconnects mid-stream; Phase 0 persists nothing for a failed turn, only an audit event. Raised in P0-14.
- Phase 1: "stop generation" button in the chat view (architecture §7.1); P0-16 does not list it. Raised in P0-16.
- Phase 1: re-ingestion and withdrawal commands (architecture §6.2: new parse, old chunks withdrawn, citations shown as superseded). P0-09 only refuses an identical file that is already ingested. Raised in P0-09.
- Phase 1: keep the original own-analysis files in platform storage for download links (architecture §6.2). P0-09 uploads to RAGFlow only. Raised in P0-09.
- Phase 1: an approval step between registering a source and ingesting it (architecture §6.2, "reviewer approves"); P0-09 ingests on the editor's command. Raised in P0-09.
- Phase 1: crawler policy items beyond P0-10 (architecture §6.4): skip special-category pages at crawl time, store raw HTML and fetch date per page, keep a per-site allow decision and scope rules in the register, per-path TDMRep rules (P0-10 treats any reservation in tdmrep.json as blocking the whole site), and site terms review. Raised in P0-10.
- Phase 1: publication dates for crawled pages from explicit page metadata only; P0-10 leaves `published_on` empty because readability libraries guess dates from body text. Raised in P0-10.
- ~~Phase 1: add `top_k`, `similarity_threshold`, `max_context_tokens` and the vector weight to the answer cache key, so a retrieval change never serves answers retrieved under old settings (findings D7). Raised in P0-18.~~ Done in P1a-05.
- Phase 1: move RAGFlow's `vector_similarity_weight` (hard-coded 0.3) into `[chat]` config and tune it with the threshold on eval set v1 (findings section 5). Raised in P0-20.
- Phase 1: a separate pinned `judge_model` for the eval harness, so the judge does not grade its own model's answers (findings D6). Raised in P0-18.
- Phase 1: eval gate in CI against staging (spec P0-19 "automatic gating"); run `compare` against the last committed baseline and block on regression. Raised in P0-19.
- Phase 1b: content console, source register approval flow, two-host deployment, retention jobs, SSO connectors (Entra, Google, OIDC/SAML); deferred from Phase 1 so that Phase 1a can ship the test client's features. Raised Oct 18, 2026.
- Phase 2: any tenant user may edit a workspace's additional-instructions prompt; every edit versioned with author and time, audited, revertible by the tenant admin. Phase 1a allows tenant admins only. Raised Oct 18, 2026.
- Phase 2: before the SOC 2 observation window, revisit the light OpenRouter paperwork (compliance addendum Oct 18, 2026): bespoke ZDR confirmation, fuller TIA, upstream vendor list review.
- Phase 2: source filters driven from the per-workspace file list (architecture §7.1); P1a-09 is a plain list with no search or filters.
- Phase 1b: spend visibility for operators beyond the 80 and 100 percent notices: per-tenant month-to-date external spend and usage by model in the operator console, read from `usage_ledger` (owner decision Oct 19, 2026). Raised at the Group B and C merge.
- Phase 2: per-model eval baselines; Phase 1a evaluates on `deepseek-v4.1-flash` only by owner decision.
- Phase 1: first-login onboarding with consent gate. When a person signs in for the first time (once Authentik replaces the Phase 0 bearer token), show the use and privacy policy in full legal wording plus a short plain-language summary of the key points, and require explicit consent to the privacy terms before the first login completes; no consent, no access. Record the consent (user, policy version, timestamp) as an audit event, and re-prompt when the policy version changes. Relates to the compliance guide's public privacy notice and acceptable-use policy. Raised by product owner.
- Phase 1b: per-IP rate limit on `POST /auth/link` (architecture §8 "per-address and per-IP"); P1a-02 caps links per user (`links_per_window`) and leaves per-IP limits to the proxy. Raised in P1a-02.
- Phase 1b: offer a session refresh before the access token expires (provider validity, `hours=8`). Revocation on sign-out is done (P1a-02, owner decision Oct 19, 2026, findings D1); the Authentik revocation call there is desk-checked only and should be checked against a live instance. Raised in P1a-02.
- Phase 1b: an Authentik blueprint for the sign-in flow, provider, scope mapping and application, once the manual configuration in `infra/authentik/README.md` has run against a live instance (findings A7). Raised in P1a-02.
- Phase 2: when the tenant audit-log download is built (architecture §7.2), leave out `workspace.prompt_tenant_name_match` events, which are for the operator only (compliance addendum Oct 18: nothing is shown to the tenant). Raised in P1a-07.
- Phase 1b: move the download content store (`[files] content_root`, a local volume on the single Instance) to Scaleway Object Storage in Paris with backup, as part of the two-host deployment; the API reads by `stored_path`, so only `app.content.store` changes. Raised in P1a-14 (findings D9).
- Phase 1b: the retention purge job also deletes `revoked_sessions` rows past their token's expiry and `downloads` rows past a retention to be set by the owner (the `download` audit events stay). Raised in Group D (findings D1, D11).
- Phase 1b: a "no history" retention (architecture §7.2 "down to 0") once the purge job exists; Phase 1a allows 1 to 30 days because expiry is applied at read time. Raised in P1a-13 (findings D7).
