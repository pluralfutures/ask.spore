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
| `./blueprints` mounted read-only at `/blueprints/custom` (P1b-08) | Our configuration is applied from a file |

## First run (dev or the Instance)

```
cp infra/authentik/.env.example infra/authentik/.env    # fill in, see comments
docker compose -f infra/compose.dev.yml --profile auth up -d   # on a fresh volume, if the
#   second container fails with "failed to create symlink ... media: file exists", run the
#   same command again: Docker populated the shared volume for the first one (CI starts them
#   one at a time)
ssh -L 9000:127.0.0.1:9000 <instance>                   # on the Instance only
open http://127.0.0.1:9000/if/flow/initial-setup/       # create the admin account
```

## Configuration the API relies on

From P1b-08 the blueprint `blueprints/ask-spore.yaml` does all of this (see
"Blueprint" below); the steps stay here as what it does and why. Names must match
`[auth.authentik]` in `config/models.toml`.

1. **Email template.** `templates/ask-spore-sign-in.html` links to the public host,
   `askspore.myceliumgastronomy.com` (owner, Oct 20, 2026; P1a-16). A second host
   (Phase 1b) needs its own template or a render step. The link carries Authentik's flow token in the *fragment* of our landing
   page (`/auth/finish#token=…`); never Authentik's own `{{ url }}`.
2. **Stages.**
   - Identification stage `ask-spore-identification`: user field *email* only, no
     password field, no sources, "Pretend user exists" on.
   - Email stage `ask-spore-email-link`: "Use global connection settings" on (the SMTP
     settings above), template `ask-spore-sign-in.html`, token expiry `minutes=15`,
     subject "Sign in to SporeBot", "Activate pending user on success" off.
   - User login stage `ask-spore-login`: session duration `hours=8`.
3. **Flow** `ask-spore-sign-in-link`, designation *Authentication*, with the three
   stages in that order, and from P1b-08 a fourth between the email stage and the login
   stage (see 3a). Authentik inserts its own one-time consent stage in front of a
   plan restored from an email token (`EmailTokenRevocationConsentStageView`); the API
   answers it.
3a. **Second factor for tenant admins** (P1b-08). Group `ask-spore-tenant-admins` (the
   API adds and removes tenant admins of tenants whose login policy requires it). TOTP
   setup stage `ask-spore-admin-totp-setup` (6 digits); authenticator validation stage
   `ask-spore-admin-mfa`: device classes *TOTP* only, "not configured" action *configure*
   with that setup stage, last-validation threshold `seconds=0`. Bind it in
   `ask-spore-sign-in-link` at order 25 (identification 10, email 20, login 30) with
   "evaluate when the flow is planned" off and "evaluate when the stage is run" on, and
   bind the group to that stage binding, so only its members are asked. The API relays the
   challenge to the browser holding the link (`POST /api/v1/auth/mfa`) and refuses a tenant
   admin who got through without it. WebAuthn cannot be relayed (the browser never talks
   to Authentik), so it is not offered here.
4. **Scope mapping** `ask_spore` (OAuth2/OpenID scope mapping, scope name `ask_spore`):
   ```python
   return {
       "ask_spore_tenant": request.user.attributes.get("ask_spore_tenant"),
       "ask_spore_sso": request.user.attributes.get("ask_spore_sso"),
   }
   ```
   `ask_spore_sso` (P1b-07) is set only on users that arrive from a tenant's SSO source:
   which source, and what the IdP said (hosted domain, address verified, admin group).
5. **Provider** `ask-spore` (OAuth2/OpenID): confidential client, client ID
   `ask-spore`, redirect URI `https://ask-spore.invalid/auth/callback` (strict),
   grant types `["authorization_code"]` at least (an empty list, the API's default when
   the field is omitted, refuses every authorize request with "Invalid grant_type for
   provider"; found in the live sign-in test, Oct 21, 2026),
   authorization flow *implicit consent*, signing key: a certificate (RS256; the API
   refuses HS256), scopes `openid email profile ask_spore offline_access`, access token
   validity `hours=8`, subject mode "Based on the User's hashed ID". From P1b-08 the grant
   types are `["authorization_code", "refresh_token"]` and the refresh token validity is
   `hours=24` (`[auth] refresh_token_ttl_seconds`): the web app renews the session five
   minutes before the access token expires; Authentik rotates the refresh token. The client secret goes in the
   root `.env` as `AUTHENTIK_CLIENT_SECRET`.
6. **Application** `ask-spore` bound to that provider.
7. **API token** for a service account allowed to view, add and change users; it goes in
   the root `.env` as `AUTHENTIK_API_TOKEN`. The operator console provisions users through
   it (`ask_spore_tenant` attribute, path `ask-spore`). From P1b-07 it also needs to view,
   add, change and delete OAuth and SAML sources, source property mappings and certificate
   key pairs, and to view flows: the console creates each tenant's SSO source through it.
7a. **Source flows** (P1b-07), used by every tenant's SSO source:
   - `ask-spore-source-authentication` (designation *Authentication*): a user write stage
     `ask-spore-source-write` ("Never create users": updates the source user from the
     mapping), then `ask-spore-login`.
   - `ask-spore-source-enrollment` (designation *Enrollment*): a user write stage
     `ask-spore-source-create` ("Always create users", path `ask-spore/sso`, "Create users
     as inactive" off), then `ask-spore-login`.
   - Both source flows carry the expression policy `ask-spore-source-if-sso`, which lets the
     flow run only for a sign-in that arrives through an SSO source (never a bare request),
     and the create stage sets `user_type: external` so SSO users are told apart from the
     internal tenant's accounts. Both are in the blueprint (`blueprints/ask-spore.yaml`).
   - `ask-spore-source-pre-authentication` (designation *Stage configuration*, no stages):
     required by SAML sources.
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

## Blueprint (P1b-08)

`blueprints/ask-spore.yaml` reproduces steps 2 to 7a: the three link-flow stages and the
flow, the admin second factor (group, TOTP setup, validation stage bound to the group), the
source flows, the `ask_spore` scope mapping, the provider (with `offline_access` and the
`refresh_token` grant) and the application, and the provisioner: service account
`ask-spore-provisioner`, role `ask-spore-provisioner` with exactly the permissions the API
uses, and an API token. It holds no secret: Authentik generates the provider's client secret
and the token's key; copy them to `AUTHENTIK_CLIENT_SECRET` and `AUTHENTIK_API_TOKEN` in the
root `.env` (admin interface: Applications → Providers → ask-spore, and Directory → Tokens).
Step 1 (the template) is the mounted `templates/` folder; steps 8 and 9 stay manual.

The worker applies it on start and when it changes. CI applies it to an empty Authentik of
the pinned version, twice (idempotent), and checks the result with
`blueprints/verify_blueprint.py` (job `authentik-blueprint`). On an Instance configured by
hand it adopts the existing objects by name or slug and changes only what differs (from
P1b-08: the `refresh_token` grant, `offline_access`, the refresh validity and the MFA
stage). There, after pulling this code and before restarting the auth profile (which
applies it), run a dry run in a one-off container (the image's entrypoint is `ak`), then
check the result once it is applied:

```
docker compose -f infra/compose.dev.yml --profile auth run --rm authentik-worker \
  apply_blueprint --dry-run custom/ask-spore.yaml
docker compose -f infra/compose.dev.yml --profile auth up -d
docker compose -f infra/compose.dev.yml --profile auth exec -T authentik-worker \
  ak shell < infra/authentik/blueprints/verify_blueprint.py
```

The live Instance's provisioner may have another username; the blueprint then adds
`ask-spore-provisioner` beside it, and the old account can be removed once its token is
replaced.

## Tenant SSO sources (P1b-07)

The operator console creates one source per tenant through the API token above, never by
hand: Entra ID (OAuth source type `entraid`, with the client's Entra tenant ID pinned in
every endpoint and the well-known URL), Google (`google`), generic OIDC (`openidconnect`,
from the issuer's well-known URL) or SAML (from the IdP's metadata; the IdP's certificate
is imported as a key pair, and the SP signing key is generated in Authentik). Each source
gets its own property mapping `ask-spore-sso-<tenant slug>`, generated by the API: it
refuses any address outside the tenant's verified domains (and, for Google, an `hd` outside
them) and sets `ask_spore_tenant` from the source's own tenant, never from a claim. Users
from a source are matched by the IdP's identifier only (`user_matching_mode: identifier`),
in the path `ask-spore/sso`, with usernames `<source slug>.<email>`, so a source user never
merges with a sign-in-link user of the same address. The client secret goes to Authentik
only; our database keeps the non-secret fields.

The browser still never talks to Authentik. The IdP sends it back to our public host
(`[auth.authentik] public_url`) under Authentik's own paths, `/source/oauth/callback/<slug>/`
and `/source/saml/<slug>/acs/`; Caddy hands exactly those two paths to the API, which
relays them to Authentik on the Compose network with our public host as `Host`, so the
redirect URI and SAML destination Authentik checks are the ones the client registered.
The console shows what the client's IT registers: the redirect URI for OIDC kinds, the ACS
URL and SP entity ID for SAML (HTTP-Redirect binding for requests). Desk-checked against
the `version-2026.8` source; the live check per kind is a release step (P1b-16).

## What Authentik does and does not do for us

Desk-checked against the `version-2026.8` source (findings §3 of Phase 0, item 3):

- (a) **Browser binding: no.** A flow token restores its plan in any browser. The API
  enforces binding itself (`app.auth.links`): the link request sets a cookie on the
  requesting browser and the completing POST must carry it.
- (b) **Single use and expiry: yes**, `token_expiry` on the email stage (plus one minute),
  and the token is deleted when the consent challenge is answered, not on GET. The API
  adds its own single-POST and 15-minute checks before calling Authentik.
- (c) **Per-tenant switch-off: not needed in Authentik.** The API sends no link for a
  tenant whose login policy (`tenant_login_policy.sign_in_links_enabled`, P1b-06) has
  links off, and refuses completion if they were switched off in between.
- (d) **SMTP over Scaleway Transactional Email (fr-par), Mailgun EU as backup:**
  configured above; delivery not yet tested. Scaleway Transactional Email does not
  rewrite links. If the Mailgun backup is ever switched on, click tracking must be off on
  the Mailgun domain: a tracking redirect would rewrite the link, and the token must stay
  in the fragment of our landing page.
