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
never served after a deploy (Phase 1a findings F10). Without it the API uses a hash of
`config/` and its own code, which also changes with any code or configuration change.

## Deploying on the Instance (P1c-10)

One script run from the live working tree (`/root/ask.spore`, which stays on `main`; branch
work uses a separate `git worktree`):

```
infra/scripts/deploy.sh --public-url https://<public host>       # main
infra/scripts/deploy.sh --commit <sha> --public-url https://<public host>
infra/scripts/deploy.sh --dry-run                                 # what CI runs
```

It does what the Phase 1b release did by hand (findings 1b §8 sections 0 and
"Resumption"), and stops at the first failure:

1. refuses a working tree with changes; fetches; fast-forwards `main` (or checks out the
   named commit, detached);
2. sets `ASK_SPORE_DEPLOY_VERSION` to the commit's 12-character hash;
3. `image-digests.py --check` (`--hub-mirror HOST` is passed through); a moved tag or a
   registry that does not answer stops the deploy;
4. `docker compose config --quiet` with the `auth` and `public` profiles;
5. records RAGFlow's document and chunk counts per dataset (`ask-spore datasets counts`)
   when the API is running;
6. builds `migrate`, `api`, `worker` and `web-build` (F1: `migrate` has its own image);
7. starts the three Authentik services only, then `run --rm migrate` and reads the
   Alembic head;
8. `--profile public up -d ragflow api worker caddy` (RAGFlow pulls in `ragflow-tei`, F3);
9. checks `/healthz` (loopback, and the public host over TLS), `auth/mode` (`oidc` unless
   `--expect-auth-mode` says otherwise), that `ragflow-tei` and `ragflow` run, the
   worker's `worker.started` line and no `worker.mail_not_configured` since the start (F2),
   and that the dataset counts equal those of step 5;
10. prints a summary: commit, deploy version, Alembic head, the checks and the counts per
    tag. No secret, address, query or document text is printed (`config --quiet` only).

A deploy clears no cache by hand: the new deploy version is in every answer-cache key, so
no answer cached by the previous code is served (`test_cache_misses_after_a_deploy`);
the old keys expire with `[chat] cache_ttl_seconds`.

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
