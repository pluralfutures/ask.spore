# Keycloak SSO drill (P1b-16, release runbook 2.4)

A throwaway generic-OIDC identity provider for the test tenant `ssotest`, on
`idp-test.askspore.myceliumgastronomy.com` (A record to the Instance). Drill only: not part
of any deploy, removed after the drill with its volume.

Realm `ask-spore-drill`, one confidential client `ask-spore-drill` (redirect URI
`https://askspore.myceliumgastronomy.com/source/oauth/callback/sso-ssotest/`), two users
with verified emails: one on a domain verified for `ssotest`, one not. Caddy exposes only
`/realms/ask-spore-drill/*` and `/resources/*`; the admin console is not reachable.

Secrets never enter the repository or a session: `setup.py` generates them into
`/srv/ask-spore/drills/` (root only). The owner reads `owner.txt` in their own terminal and
types the client secret into the operator console.

```
python3 infra/drills/keycloak/setup.py --verified-email <user@verified-domain> \
  --outsider-email <user@other-domain>
D="-f infra/compose.dev.yml -f infra/drills/keycloak/compose.yml"
docker compose $D --profile drill up -d idp-test-keycloak
docker compose $D --profile public up -d --no-deps caddy
```

Remove after the drill (named objects only):

```
docker compose $D --profile drill rm -sf idp-test-keycloak
docker volume rm ask-spore-dev_keycloak_drill
docker compose -f infra/compose.dev.yml --profile public up -d --no-deps caddy
rm /srv/ask-spore/drills/owner.txt /srv/ask-spore/drills/keycloak.env \
  /srv/ask-spore/drills/realm/ask-spore-drill.json
rmdir /srv/ask-spore/drills/realm /srv/ask-spore/drills
```
