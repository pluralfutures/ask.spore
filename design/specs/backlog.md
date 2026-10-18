# Backlog

Ideas and deferred items raised during a phase that belong to a later phase. One line each, with the phase it belongs to.

- Phase 1: pin container images by digest, not only by tag (architecture §8 "Hardening"); Phase 0 pins exact tags. Raised in P0-02.
- Phase 1: write auth events (success, failure with method) to `audit_events` once Authentik replaces the Phase 0 bearer token; P0-06 only logs rejections. Raised in P0-06.
- Phase 1: decide the production path for the RAGFlow web UI, whose nginx also proxies RAGFlow's API (findings R3): keep it on the Private Network only, or front it with an authenticating proxy. Raised in P0-02.
- Phase 1: replace the 4-characters-per-token estimate (history and context caps) with Mistral's tokenizer. Raised in P0-14.
- Phase 1: keep the question (and a partial answer, flagged) when the model fails or the client disconnects mid-stream; Phase 0 persists nothing for a failed turn, only an audit event. Raised in P0-14.
- Phase 1: "stop generation" button in the chat view (architecture §7.1); P0-16 does not list it. Raised in P0-16.
- Phase 1: re-ingestion and withdrawal commands (architecture §6.2: new parse, old chunks withdrawn, citations shown as superseded). P0-09 only refuses an identical file that is already ingested. Raised in P0-09.
- Phase 1: keep the original own-analysis files in platform storage for download links (architecture §6.2). P0-09 uploads to RAGFlow only. Raised in P0-09.
- Phase 1: an approval step between registering a source and ingesting it (architecture §6.2, "reviewer approves"); P0-09 ingests on the editor's command. Raised in P0-09.
- Phase 1: crawler policy items beyond P0-10 (architecture §6.4): skip special-category pages at crawl time, store raw HTML and fetch date per page, keep a per-site allow decision and scope rules in the register, per-path TDMRep rules (P0-10 treats any reservation in tdmrep.json as blocking the whole site), and site terms review. Raised in P0-10.
- Phase 1: publication dates for crawled pages from explicit page metadata only; P0-10 leaves `published_on` empty because readability libraries guess dates from body text. Raised in P0-10.
- Phase 1: add `top_k`, `similarity_threshold`, `max_context_tokens` and the vector weight to the answer cache key, so a retrieval change never serves answers retrieved under old settings (findings D7). Raised in P0-18.
- Phase 1: move RAGFlow's `vector_similarity_weight` (hard-coded 0.3) into `[chat]` config and tune it with the threshold on eval set v1 (findings section 5). Raised in P0-20.
- Phase 1: a separate pinned `judge_model` for the eval harness, so the judge does not grade its own model's answers (findings D6). Raised in P0-18.
- Phase 1: eval gate in CI against staging (spec P0-19 "automatic gating"); run `compare` against the last committed baseline and block on regression. Raised in P0-19.
- Phase 1: first-login onboarding with consent gate. When a person signs in for the first time (once Authentik replaces the Phase 0 bearer token), show the use and privacy policy in full legal wording plus a short plain-language summary of the key points, and require explicit consent to the privacy terms before the first login completes; no consent, no access. Record the consent (user, policy version, timestamp) as an audit event, and re-prompt when the policy version changes. Relates to the compliance guide's public privacy notice and acceptable-use policy. Raised by product owner.
