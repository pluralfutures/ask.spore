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

## Backups: content store copy and restore test (P1c-12)

The owner's nightly backup copies the Instance's Docker volumes (Phase 1b release,
Oct 22, 2026). Two additions, run by the release session with the owner (P1c-16):

### Nightly copy of the content store

`[files] content_root` is the `content` volume (`ask-spore-dev_content`, mounted at
`/srv/ask-spore/content` in the api and worker): stored copies of ingested files, crawled
pages with their raw HTML, and the certificates of deletion. Copy it each night next to the
volume backup, read-only, as root:

```
# /etc/cron.d/ask-spore-content (root): 02:30 UTC, 14 nightly copies kept
30 2 * * * root install -d -m 0700 /srv/backups/content && docker run --rm --network none \
  -v ask-spore-dev_content:/content:ro -v /srv/backups/content:/backup \
  alpine:3.22@sha256:<pinned digest> \
  sh -c 'tar -czf /backup/content-$(date -u +\%Y\%m\%d).tgz -C /content . && \
         find /backup -name "content-*.tgz" -mtime +14 -delete'
```

Pin the helper image's digest with `image-digests.py` before installing the line, and use
the backup destination and retention the volume backup already uses (the certificate of
deletion says backups made before a deletion age out under that retention). The copy holds
publisher files and certificates: it stays on the Instance's backup path, root only,
like the volumes. `/srv/ask-spore/eval-runs/` (full eval outputs) is not part of it.

### Restore test (run once per phase, recorded in the findings)

Restore the latest nightly backup into a **scratch Compose project** next to the live one
and compare counts. Nothing of the scratch project is published beyond loopback, it uses
other host ports, and it is removed afterwards with its volumes. Commands as root from the
live tree; `R` names the scratch project.

1. Note the backup's date and the live figures at the same time (counts only):

   ```
   docker compose -f infra/compose.dev.yml exec -T postgres psql -U askspore -d askspore -At \
     -c "SELECT format('SELECT %L, count(*) FROM %I', table_name, table_name)
         FROM information_schema.tables WHERE table_schema = 'public'
         AND table_type = 'BASE TABLE' ORDER BY 1 \gexec" > /root/restore-live-rows.txt
   docker compose -f infra/compose.dev.yml exec -T api ask-spore datasets counts \
     | python3 -c 'import json,sys; [print(r["tag"], r["count"], r["chunk_count"]) for r in map(json.loads, sys.stdin) if r.get("event") == "datasets.counts"]' \
     | sort > /root/restore-live-datasets.txt
   ```

   Rows written between the backup and now make some counts differ; note the time of each.

2. Create the scratch volumes and restore into them, one per backed-up volume:
   `postgres_data`, RAGFlow's Elasticsearch, MySQL and MinIO volumes, and `content`
   (`docker volume ls --filter name=ask-spore-dev_` lists the live names). With the backup
   as volume archives, for each `<vol>`:

   ```
   R=askspore-restore
   docker volume create "${R}_<vol>"
   docker run --rm --network none -v "${R}_<vol>:/v" -v /srv/backups:/b:ro alpine:3.22@sha256:<pinned digest> \
     tar -xzf "/b/<the backup's archive of ask-spore-dev_<vol>>" -C /v
   ```

   (With another backup format, restore it into the same `${R}_<vol>` volumes.)

3. Start the data services only, on other loopback ports, without the application:

   ```
   export POSTGRES_PORT=15432 REDIS_PORT=16379 API_PORT=18000 RAGFLOW_UI_PORT=18080
   docker compose -p "$R" -f infra/compose.dev.yml up -d postgres ragflow
   ```

   `ragflow` pulls in its Elasticsearch, MySQL, MinIO, Redis and TEI. No migration runs:
   the restored database is compared as it was backed up.

4. The same figures from the restored copy (the scratch api container reaches the scratch
   Postgres and RAGFlow on the project's own networks; `--no-deps` starts nothing else; the
   first `run` builds the scratch project's api image from the live tree, a few minutes):

   ```
   docker compose -p "$R" -f infra/compose.dev.yml exec -T postgres psql -U askspore -d askspore -At \
     -c "<the same SELECT as in step 1>" > /root/restore-scratch-rows.txt
   docker compose -p "$R" -f infra/compose.dev.yml run --rm --no-deps api ask-spore datasets counts \
     | python3 -c '<the same filter as in step 1>' | sort > /root/restore-scratch-datasets.txt
   diff /root/restore-live-rows.txt /root/restore-scratch-rows.txt
   diff /root/restore-live-datasets.txt /root/restore-scratch-datasets.txt
   ```

   Also: `ls` of the restored `content` volume's file count against the live one
   (`docker run --rm -v "${R}_content:/c:ro" alpine:3.22@sha256:<pinned digest> sh -c 'find /c -type f | wc -l'`).

5. Record in the phase's findings: the backup's date, the restore duration, every table and
   dataset count (live, restored, and why any differ: rows written after the backup), the
   content file counts. Counts only; never a row, a file name or document text.

6. Remove the scratch project and its volumes, and the comparison files:

   ```
   docker compose -p "$R" -f infra/compose.dev.yml down -v
   docker volume ls --filter "name=${R}_" -q | xargs -r docker volume rm
   rm /root/restore-*.txt
   ```

A restore that does not start, or counts that differ for any reason other than writes after
the backup, is a finding for the owner before the next client user is invited.
