# infra/caddy

Phase 1+. Not used in Phase 0 (see design/specs/phase-0-build-spec.md, "Not in this phase").

When Caddy is configured (Phase 1a, one host with TLS): do not enable request logging of
paths under `/api/v1/files/`, which carry single-use download tokens (P1a-14), or log
paths without them. Caddy's default is no access log.
