# Backlog

Ideas and deferred items raised during a phase that belong to a later phase. One line each, with the phase it belongs to.

- Phase 1: pin container images by digest, not only by tag (architecture §8 "Hardening"); Phase 0 pins exact tags. Raised in P0-02.
- Phase 1: write auth events (success, failure with method) to `audit_events` once Authentik replaces the Phase 0 bearer token; P0-06 only logs rejections. Raised in P0-06.
- Phase 1: decide the production path for the RAGFlow web UI, whose nginx also proxies RAGFlow's API (findings R3): keep it on the Private Network only, or front it with an authenticating proxy. Raised in P0-02.
- Phase 1: re-ingestion and withdrawal commands (architecture §6.2: new parse, old chunks withdrawn, citations shown as superseded). P0-09 only refuses an identical file that is already ingested. Raised in P0-09.
- Phase 1: keep the original own-analysis files in platform storage for download links (architecture §6.2). P0-09 uploads to RAGFlow only. Raised in P0-09.
- Phase 1: an approval step between registering a source and ingesting it (architecture §6.2, "reviewer approves"); P0-09 ingests on the editor's command. Raised in P0-09.
