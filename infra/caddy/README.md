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
| `/.well-known/security.txt`, `/security-disclosure` | the web build's `public/` files as they are (P2A-11): no `index.html`, no API call, so no sign-in and no consent gate. Source text: `design/compliance/security-disclosure.md` |
| `/trust` | 404 unless `ASKSPORE_TRUST_PAGE=published` (in `infra/.env`, passed by Compose; default `unpublished`), then `trust.html` of the web build. The build has no `trust.html` yet: the owner adds it from `design/compliance/trust-page.md` once paperwork item 4 clears. Any other value stops Caddy at start. `/trust.html` and `/security-disclosure.html` themselves are 404 |
| `/legal`, `/legal/privacy`, `/legal/ai`, `/legal/terms` | 404 unless `ASKSPORE_LEGAL=published` (in `infra/.env`, passed by Compose; default `unpublished`), then the web build's `legal/*.html`, rendered from `design/compliance` by `apps/web/scripts/render-legal.mjs` (P2A-L2). The footer's "Legal" link points at `/legal`. Public: no sign-in, no cookie, no API call. Any other flag value stops Caddy at start. The files' own `.html` names are 404 |
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
