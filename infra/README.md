# infra

| File | Purpose |
| --- | --- |
| `compose.dev.yml` | Local stack: Postgres 16, Redis 7, API, web dev server, and RAGFlow (included from `ragflow/`) |
| `ragflow/` | Pinned RAGFlow Compose, `VERSION`, `.env.example`; see its README for differences from upstream |
| `authentik/` | Pinned Authentik Compose (P1a-02, profile `auth`), sign-in email template, `.env.example`; see its README for differences from upstream and the configuration the API relies on |
| `caddy/` | Caddyfile for the one public host with TLS (Phase 1a release, profile `public`); see its README |
| `monitoring/` | Phase 1+ |

## Local stack

```
cp infra/ragflow/.env.example infra/ragflow/.env      # set passwords
docker compose -f infra/compose.dev.yml up -d
```

| Service | URL (host) | Notes |
| --- | --- | --- |
| API | http://127.0.0.1:8000/healthz | |
| Web | http://127.0.0.1:5173 | Vite dev server, `src/` bind-mounted |
| RAGFlow UI | http://127.0.0.1:8080 | Loopback only; the UI port also proxies RAGFlow's API, so never publish it beyond loopback or the firewall |
| Postgres | 127.0.0.1:5432 | db `askspore`; owner `askspore` (`POSTGRES_PASSWORD`, dev `askspore-dev`) runs migrations; the API logs in as `askspore_app` (`APP_DB_PASSWORD`, dev `askspore-app-dev`), which is not the owner, so row-level security applies |
| Redis | 127.0.0.1:6379 | |
| Authentik admin | http://127.0.0.1:9000 | Only with `--profile auth`. Loopback only, never a public port: browsers never talk to Authentik, the API reaches it at `http://authentik-server:9000` on the `authentik` network |

Sign-in links (P1a-02) need the `auth` profile and `[auth] mode = "oidc"` in
`config/models.toml`; `mode = "phase0"` keeps the Phase 0 bearer token for the eval
harness. See `authentik/README.md`.

All host ports bind to `127.0.0.1`, except Caddy's 80 and 443 (profile `public`, `up -d caddy`). RAGFlow's Elasticsearch, MySQL, MinIO, Redis, TEI
and HTTP API (`9380`) publish nothing; the API container reaches RAGFlow at
`http://ragflow:9380` on the `ragflow` network.

Deploys set `ASK_SPORE_DEPLOY_VERSION` (P1b-13 e), which the API and worker read at
startup and put in the answer cache key, so answers cached by the previous code are
never served after a deploy (Phase 1a findings F10):

```
ASK_SPORE_DEPLOY_VERSION=$(git rev-parse --short=12 HEAD) docker compose -f infra/compose.dev.yml up -d --build api worker
```

Without it the API uses a hash of `config/` and its own code, which also changes with
any code or configuration change.

The one-shot `migrate` service runs `alembic upgrade head` as the owner before the API
starts. `PHASE0_INTERNAL_USERS` in the root `.env` lists the users the first migration
seeds. `infra/postgres/10-app-role.sh` creates the `askspore_app` login role on a fresh
volume only.

To run the API or web app on the host with `--reload` instead (the commands in
`CLAUDE.md`), start only the backing services so the ports do not clash:

```
docker compose -f infra/compose.dev.yml up -d postgres redis ragflow
set -a; . ./.env; set +a          # DATABASE_URL, MIGRATIONS_DATABASE_URL, secrets
uv run --directory apps/api alembic upgrade head
```

Host requirement for Elasticsearch: `sysctl -w vm.max_map_count=262144`.
Disk: the RAGFlow and TEI images are about 24 GB together.

## Image pins (P1b-15 g)

Every image is pinned by tag and digest (`name:tag@sha256:…`): Compose files, the API and web
Dockerfiles and the CI PostgreSQL service. `apps/api/tests/test_image_pins.py` fails on any
reference without a digest. To print the current digests, check the pins, or upgrade an image:

```
python3 infra/scripts/image-digests.py            # each reference and its tag's digest now
python3 infra/scripts/image-digests.py --check    # exit 1 if a pinned tag has moved
# change a tag, then pin it:
python3 infra/scripts/image-digests.py --write
```

Docker Hub allows 100 anonymous manifest requests an hour per address; behind a shared address
add `--hub-mirror mirror.gcr.io` (same content-addressed digests; a mirror can lag a re-pushed
tag, so `--check` against Docker Hub before trusting a changed digest). The pins of Oct 22, 2026
were taken through that mirror for Docker Hub images and from ghcr.io directly for Authentik.

## Credentials rotation (P1c-03)

The `.env.example` files, the Compose defaults (`${POSTGRES_PASSWORD:-askspore-dev}`,
`${APP_DB_PASSWORD:-askspore-app-dev}`) and the CI workflow publish passwords for local
stacks. No deployment users sign in to may run on them:

- **Startup check.** In `[auth] mode = "oidc"` the API, the worker and the CLI refuse to
  start when a secret they read, or the password of `DATABASE_URL`,
  `MIGRATIONS_DATABASE_URL` or `REDIS_URL`, equals a published value
  (`app/core/credentials.py`). The error names the keys, never the values. Phase 0 mode
  (the loopback dev and eval stack) is not checked.
- **Host check.** `python3 infra/scripts/check-credentials.py` compares `.env`,
  `infra/.env` (Compose interpolation), `infra/authentik/.env` and `infra/ragflow/.env`
  with the published values, including the services the API never sees; it also fails on
  an unset `POSTGRES_PASSWORD` or `APP_DB_PASSWORD` (Compose would use its default) and on
  any `AUTHENTIK_BOOTSTRAP_*` key. Exit 1 and key names only.

The owner runs the rotation in their own terminal on the Instance. **Secrets never pass
through a session**: a session may run the two checks and read their key names, nothing
else. Generate each value with `openssl rand -hex 32` (hex: safe in a URL, no quoting), type
or paste it only into the prompts and files below, and keep every `.env` at mode 0600.
Run the commands from the repository root with `C="docker compose -f infra/compose.dev.yml"`.
The Phase 1c code refuses to start on the Instance until step 1 is done, so do it before
(or as the first step of) the deploy that brings P1c-03.

1. **Database roles** (the application database). Roles with LOGIN: the schema owner
   `askspore` and the application role `askspore_app`; `askspore_auth`, `askspore_operator`,
   `askspore_content` and `askspore_retention` are NOLOGIN (no password) and stay so.
   1. `$C exec postgres psql -U askspore -d askspore`, then `\password askspore` and
      `\password askspore_app` (psql prompts twice for each and sends only the SCRAM hash,
      so the value is in no shell history or server log); `\q`.
   2. In `infra/.env` (the Compose interpolation file; create it, mode 0600) set
      `POSTGRES_PASSWORD=` and `APP_DB_PASSWORD=` to the two new values. Compose passes
      them to `migrate` (owner DSN), `api` and `worker` (`DATABASE_URL`) and, on a fresh
      volume only, to Postgres and `infra/postgres/10-app-role.sh`.
   3. In the root `.env`, replace the password in `MIGRATIONS_DATABASE_URL` and, if
      present, `DATABASE_URL` (host-run tools) with the same values.
   4. `$C up -d --force-recreate migrate api worker`; `migrate` exits 0, `/healthz` 200,
      the worker logs its startup line. A refusal names the keys still published.
2. **Authentik bootstrap token and admin password.**
   1. Remove every `AUTHENTIK_BOOTSTRAP_*` line from `infra/authentik/.env` (Authentik
      re-creates the bootstrap token from them when it starts).
   2. `$C --profile auth up -d --force-recreate authentik-server authentik-worker`.
   3. Over the SSH tunnel (`ssh -L 9000:127.0.0.1:9000 <instance>`), signed in as
      `akadmin`: Directory → Tokens, delete `authentik-bootstrap-token` (first check that
      `AUTHENTIK_API_TOKEN` in the root `.env` is the provisioner's token
      `ask-spore-provisioner-api`, not this one); then the user menu → Settings → Change
      password for `akadmin`, and enrol a TOTP device for it if it has none.
   4. Optional, if `POSTGRES_PASSWORD` / `AUTHENTIK_POSTGRESQL__PASSWORD` in
      `infra/authentik/.env` were ever shared: `$C --profile auth exec authentik-postgresql
      psql -U authentik -d authentik`, `\password authentik`, set both keys to the new
      value, recreate the three Authentik services. `AUTHENTIK_SECRET_KEY` is not rotated
      in place (it signs sessions and encrypts stored secrets; changing it signs everyone
      out of the admin interface).
   5. Check: an operator sign-in link still arrives and signs in; the api logs no
      `authentik_unavailable`.
3. **RAGFlow** (`infra/ragflow/.env`; the Phase 1b release found these already differ
   from the example, so only if the host check names one):
   - `REDIS_PASSWORD` (Valkey, set on its command line) and `MINIO_PASSWORD` (MinIO's root
     credentials, read from the environment at start): change the value, then
     `$C up -d --force-recreate ragflow-redis ragflow-minio ragflow`.
   - `MYSQL_PASSWORD` (stored in the MySQL volume): `$C exec ragflow-mysql mysql -uroot -p`,
     then `ALTER USER 'root'@'%' IDENTIFIED BY '<new>';` typed at the prompt, then set the
     key and recreate `ragflow-mysql` and `ragflow`.
   - `ELASTIC_PASSWORD` (stored in Elasticsearch's security index):
     `$C exec ragflow-es bin/elasticsearch-reset-password -u elastic -i`, then set the
     key and recreate `ragflow-es` and `ragflow`.
   - `RAGFLOW_API_KEY` (root `.env`): create a new key in the RAGFlow UI (loopback,
     avatar → API), set it, `$C up -d --force-recreate api worker`, then delete the old
     key in the UI.
   - Check: RAGFlow healthy, its document counts per dataset unchanged, one question
     answered with citations.
4. **Redis (application).** No password is set: `redis` listens on the Compose network
   and on loopback only, and `REDIS_URL` carries no secret, so there is nothing to rotate.
   If one is ever set (`--requirepass` in `compose.dev.yml` and
   `REDIS_URL=redis://:<password>@redis:6379/0`), rotate it like `REDIS_PASSWORD` above.
5. **Verify.** `python3 infra/scripts/check-credentials.py` prints `ok`; the api starts.
   Record in the findings the date and which steps ran (names only).
