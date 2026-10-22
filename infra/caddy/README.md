# infra/caddy

Phase 1a release: one host, `askspore.myceliumgastronomy.com`, with TLS (release
runbook section 3). Not used in Phase 0.

```
docker compose -f infra/compose.dev.yml up -d caddy
```

`caddy` and the one-shot `web-build` are in the Compose profile `public`; naming `caddy`
starts both. `web-build` builds `apps/web/Dockerfile` and copies `dist/` into the
`web_dist` volume, which Caddy serves read-only. After a web change, run
`up -d --build web-build`; Caddy reads files per request, so it needs no restart.

| Path | Goes to |
| --- | --- |
| `/api/*`, `/healthz` | `api:8000` |
| `/source/oauth/callback/<slug>/`, `/source/saml/<slug>/acs/` | `api:8000`, rewritten to `/api/v1/auth/sso/oauth/<slug>` and `/api/v1/auth/sso/saml/<slug>`: a tenant IdP's answer, which the API relays to Authentik (P1b-07). Nothing else of Authentik is reachable |
| everything else, including `/auth/finish` | the production web build; unknown paths fall back to `index.html` (client-side routes) |

- Certificates: automatic from Let's Encrypt, account email the operator's, stored in the
  `caddy_data` volume. Ports 80 and 443 (TCP, and UDP for HTTP/3) are the only ports in
  the stack published on all interfaces.
- Headers: HSTS (one year), `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy:
  no-referrer`, a restrictive `Permissions-Policy`, and a CSP allowing only `'self'` (the
  build has no inline scripts or styles). The `Server` header is removed.
- No access log: paths under `/api/v1/files/` carry single-use download tokens (P1a-14).
  Caddy writes no access log unless a `log` directive is present; do not add one. The API
  runs with `--no-access-log` for the same reason.
- The admin endpoint is off (`admin off`), so a Caddyfile change needs `restart caddy`.
