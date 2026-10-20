# infra/authentik

Authentik identity broker for sign-in links (P1a-02). Version: see `VERSION`
(currently `2026.8.4`, the default tag of the official Compose file on the
`version-2026.8` branch).

`docker-compose.yml` is derived from upstream `lifecycle/container/compose.yml` at that
branch. Differences, to re-apply on upgrade:

| Change | Why |
| --- | --- |
| Services renamed `authentik-postgresql`, `authentik-server`, `authentik-worker`; own `authentik` network | No clashes with the app's `postgres` when included from `infra/compose.dev.yml`; the API joins `authentik` to reach `http://authentik-server:9000` |
| Image tag pinned in the file (`2026.8.4`), Postgres pinned to `16.15-alpine` (upstream `16-alpine`) | No floating tags |
| Port 9443 dropped; 9000 published on `127.0.0.1` only | Browsers never talk to Authentik (the API runs the flow); the admin interface is for the operator over an SSH tunnel, never a public port |
| Worker's `/var/run/docker.sock` and `./certs` mounts removed | No outposts; the worker must not control the Docker host |
| Named volumes instead of `./data`; `./templates` mounted read-only at `/templates` (upstream `./custom-templates`) | The sign-in email template is versioned here |
| Secrets read from `./.env` as container environment, not Compose interpolation; services behind the `auth` profile | The Phase 0 stack must keep starting without Authentik secrets; without `.env` the containers refuse to start |
| SMTP over STARTTLS on port 587; host, port and credentials in `.env` | Stack decision (Oct 20, 2026): Scaleway Transactional Email (fr-par, `smtp.tem.scw.cloud`) is the primary relay, Mailgun EU (`smtp.eu.mailgun.org`) the optional backup; Authentik's email stage only speaks SMTP |
| Update check, error reporting and startup analytics off | No calls home |

## First run (dev or the Instance)

```
cp infra/authentik/.env.example infra/authentik/.env    # fill in, see comments
docker compose -f infra/compose.dev.yml --profile auth up -d
ssh -L 9000:127.0.0.1:9000 <instance>                   # on the Instance only
open http://127.0.0.1:9000/if/flow/initial-setup/       # create the admin account
```

## Configuration the API relies on

Done once in the admin interface (no blueprint yet: the flow has not been run against
a live instance, findings A7). Names must match `[auth.authentik]` in
`config/models.toml`.

1. **Email template.** Replace `__ASK_SPORE_PUBLIC_HOST__` in
   `templates/ask-spore-sign-in.html` with the public hostname before starting the
   containers. The link carries Authentik's flow token in the *fragment* of our landing
   page (`/auth/finish#token=…`); never Authentik's own `{{ url }}`.
2. **Stages.**
   - Identification stage `ask-spore-identification`: user field *email* only, no
     password field, no sources, "Pretend user exists" on.
   - Email stage `ask-spore-email-link`: "Use global connection settings" on (the SMTP
     settings above), template `ask-spore-sign-in.html`, token expiry `minutes=15`,
     subject "Sign in to ask.spore", "Activate pending user on success" off.
   - User login stage `ask-spore-login`: session duration `hours=8`.
3. **Flow** `ask-spore-sign-in-link`, designation *Authentication*, with the three
   stages in that order. Authentik inserts its own one-time consent stage in front of a
   plan restored from an email token (`EmailTokenRevocationConsentStageView`); the API
   answers it.
4. **Scope mapping** `ask_spore` (OAuth2/OpenID scope mapping, scope name `ask_spore`):
   ```python
   return {"ask_spore_tenant": request.user.attributes.get("ask_spore_tenant")}
   ```
5. **Provider** `ask-spore` (OAuth2/OpenID): confidential client, client ID
   `ask-spore`, redirect URI `https://ask-spore.invalid/auth/callback` (strict),
   authorization flow *implicit consent*, signing key: a certificate (RS256; the API
   refuses HS256), scopes `openid email profile ask_spore`, access token validity
   `hours=8`, subject mode "Based on the User's hashed ID". The client secret goes in the
   root `.env` as `AUTHENTIK_CLIENT_SECRET`.
6. **Application** `ask-spore` bound to that provider.
7. **API token** for a service account allowed to view, add and change users; it goes in
   the root `.env` as `AUTHENTIK_API_TOKEN`. The operator console provisions users through
   it (`ask_spore_tenant` attribute, path `ask-spore`).
8. Set `[auth] mode = "oidc"` in `config/models.toml` and restart the API.
9. Grant the first operator (as the schema owner; it creates the internal-tenant user,
   provisions it in Authentik and audits the grant):
   ```
   docker compose -f infra/compose.dev.yml run --rm \
     -e MIGRATIONS_DATABASE_URL=postgresql+asyncpg://askspore:<owner password>@postgres:5432/askspore \
     api ask-spore operators grant --email <operator email> --name "<name>"
   ```
   The operator then signs in with a link and opens `/operator`. Require a hardware key
   for operators in Authentik (an authenticator validation stage bound to them).

## What Authentik does and does not do for us

Desk-checked against the `version-2026.8` source (findings §3 of Phase 0, item 3):

- (a) **Browser binding: no.** A flow token restores its plan in any browser. The API
  enforces binding itself (`app.auth.links`): the link request sets a cookie on the
  requesting browser and the completing POST must carry it.
- (b) **Single use and expiry: yes**, `token_expiry` on the email stage (plus one minute),
  and the token is deleted when the consent challenge is answered, not on GET. The API
  adds its own single-POST and 15-minute checks before calling Authentik.
- (c) **Per-tenant switch-off: not needed in Authentik.** The API sends no link for a
  tenant whose `sign_in_links_enabled` is off, and refuses completion if it was switched
  off in between.
- (d) **SMTP over Scaleway Transactional Email (fr-par), Mailgun EU as backup:**
  configured above; delivery not yet tested. Scaleway Transactional Email does not
  rewrite links. If the Mailgun backup is ever switched on, click tracking must be off on
  the Mailgun domain: a tracking redirect would rewrite the link, and the token must stay
  in the fragment of our landing page.
