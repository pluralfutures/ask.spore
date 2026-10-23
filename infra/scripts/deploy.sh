#!/usr/bin/env bash
# Deploy ask.spore on the Instance (P1c-10): what the Phase 1b release did by hand
# (findings 1b §8 sections 0 and "Resumption", the release session notes' resume plan),
# as one script run from the live working tree.
#
#   infra/scripts/deploy.sh                      # pull main and deploy it
#   infra/scripts/deploy.sh --commit <sha>       # deploy a named commit (detached HEAD)
#   infra/scripts/deploy.sh --dry-run            # CI: compose config and the digest check only
#
# Options:
#   --commit SHA          deploy this commit instead of origin/main
#   --hub-mirror HOST     passed to image-digests.py (Docker Hub's anonymous limit is 100
#                         manifest requests an hour per address; a mirror can lag a re-pushed tag)
#   --public-url URL      also check /healthz over TLS on the public host (https://...)
#   --expect-auth-mode M  the auth mode the API must report (default: oidc)
#   --timeout SECONDS     how long to wait for the API to answer (default: 300)
#   --dry-run             compose config (every profile) and the digest check; nothing else
#
# Steps, in order; any failure stops the script (fail closed) with a non-zero exit:
#   1. the working tree is clean; fetch; check out origin/main (fast-forward) or the commit
#   2. ASK_SPORE_DEPLOY_VERSION = the commit's 12-character hash (in the answer cache key,
#      so answers cached by the previous code are never served: P1b-13 e)
#   3. image digests: infra/scripts/image-digests.py --check (a moved tag or an unreachable
#      registry stops the deploy)
#   4. docker compose config --quiet with the auth and public profiles
#   5. RAGFlow's dataset counts before (when the API is running), for step 9
#   6. build every image we build: migrate, api, worker, web-build (Phase 1b F1)
#   7. the three Authentik services; migrations (`run --rm migrate`) and the Alembic head
#   8. RAGFlow with its embedding service (the Compose dependency, Phase 1b F3), api,
#      worker, Caddy
#   9. checks: /healthz (loopback, and the public host if given), auth/mode, ragflow-tei
#      running, the worker's startup line and no `worker.mail_not_configured` since the
#      start, RAGFlow's dataset counts equal to those before
#  10. a metadata-only summary: no secret, address, query or document text is printed.
#
# Secrets stay in .env and infra/*/.env; this script never prints them (`config --quiet`
# only, no environment dumps).

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT/infra/compose.dev.yml"
COMMIT=""
HUB_MIRROR=""
PUBLIC_URL=""
EXPECT_AUTH_MODE="oidc"
TIMEOUT=300
DRY_RUN=0

usage() { sed -n '2,36p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
fail() { printf 'deploy: FAILED at %s: %s\n' "$STEP" "$1" >&2; exit 1; }
step() { STEP="$1"; printf '\n== %s\n' "$1"; }
STEP="arguments"

while [ $# -gt 0 ]; do
  case "$1" in
    --commit) COMMIT="${2:?--commit needs a commit}"; shift 2 ;;
    --hub-mirror) HUB_MIRROR="${2:?--hub-mirror needs a host}"; shift 2 ;;
    --public-url) PUBLIC_URL="${2:?--public-url needs a URL}"; shift 2 ;;
    --expect-auth-mode) EXPECT_AUTH_MODE="${2:?}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) printf 'deploy: unknown option %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done
if [ -n "$COMMIT" ] && ! [[ "$COMMIT" =~ ^[0-9a-f]{7,40}$ ]]; then
  fail "--commit takes a commit hash (7 to 40 hex characters)"
fi
[[ "$TIMEOUT" =~ ^[0-9]+$ ]] || fail "--timeout takes a number of seconds"
case "$PUBLIC_URL" in "" | https://*) ;; *) fail "--public-url must be https://" ;; esac

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }
# Captured first and searched after: a grep -q that stops reading early would make the
# producer fail on a closed pipe under pipefail.
running() { compose ps --status running --services 2>/dev/null || true; }
since_start() { compose logs --no-log-prefix --since "$STARTED" "$@" 2>/dev/null || true; }
# Every profile, so config and builds see every service.
compose_all() { compose --profile auth --profile public "$@"; }

digest_check() {
  local args=(--check)
  [ -n "$HUB_MIRROR" ] && args+=(--hub-mirror "$HUB_MIRROR")
  # Pinned references are printed one per line; only the moved or unpinned ones matter.
  if ! python3 "$ROOT/infra/scripts/image-digests.py" "${args[@]}" >"$WORK/digests.txt"; then
    grep -v '(pinned)$' "$WORK/digests.txt" >&2 || true
    fail "an image tag moved or a registry did not answer; nothing was deployed"
  fi
  printf 'image pins: %s match\n' "$(grep -c '(pinned)$' "$WORK/digests.txt")"
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [ "$DRY_RUN" = 1 ]; then
  step "compose config (dry run)"
  compose_all config --quiet || fail "docker compose config"
  printf 'compose config: ok\n'
  step "image digests (dry run)"
  digest_check
  printf '\ndeploy: dry run passed (nothing built, started or changed)\n'
  exit 0
fi

command -v docker >/dev/null || fail "docker is not installed"
command -v curl >/dev/null || fail "curl is not installed"
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

step "1. source"
cd "$ROOT"
[ -z "$(git status --porcelain)" ] || fail "the working tree has changes; deploy from a clean tree"
git fetch --quiet origin
if [ -n "$COMMIT" ]; then
  git cat-file -e "$COMMIT^{commit}" 2>/dev/null || fail "no such commit: $COMMIT"
  git checkout --quiet --detach "$COMMIT"
  printf 'checked out %s (detached; config/ follows it)\n' "$(git rev-parse --short=12 HEAD)"
else
  git checkout --quiet main
  git merge --quiet --ff-only origin/main || fail "main does not fast-forward to origin/main"
  printf 'main at %s\n' "$(git rev-parse --short=12 HEAD)"
fi
FULL_SHA="$(git rev-parse HEAD)"
export ASK_SPORE_DEPLOY_VERSION="${FULL_SHA:0:12}"

step "2. deploy version"
printf 'ASK_SPORE_DEPLOY_VERSION=%s\n' "$ASK_SPORE_DEPLOY_VERSION"

step "3. image digests"
digest_check

step "4. compose config"
compose_all config --quiet || fail "docker compose config (an env file or variable is missing)"
printf 'compose config: ok\n'

# RAGFlow's own counts per dataset, as `tag documents chunks` lines (metadata only).
dataset_counts() {
  compose exec -T api ask-spore datasets counts 2>/dev/null |
    python3 -c '
import json, sys
for line in sys.stdin:
    try:
        row = json.loads(line)
    except ValueError:
        continue
    if row.get("event") == "datasets.counts":
        print(row.get("tag"), row.get("count"), row.get("chunk_count"))
' | sort
}

step "5. dataset counts before"
if grep -qx api <<<"$(running)"; then
  dataset_counts >"$WORK/counts.before" || true
  printf '%s datasets counted\n' "$(wc -l <"$WORK/counts.before" | tr -d ' ')"
else
  : >"$WORK/counts.before"
  printf 'api not running: no figures to compare with\n'
fi

step "6. build"
compose_all build migrate api worker web-build || fail "image build"

step "7. Authentik, then migrations"
# The three Authentik services only: a bare `--profile auth up -d` would also start the
# api, worker and RAGFlow on the previous images (Phase 1b release, section 0.4).
compose --profile auth up -d authentik-postgresql authentik-server authentik-worker ||
  fail "Authentik services"
compose run --rm migrate || fail "alembic upgrade head"
HEAD_REVISION="$(compose run --rm migrate alembic current 2>/dev/null |
  grep -Eo '^[0-9a-z_]+ \(head\)' | cut -d' ' -f1 || true)"
[ -n "$HEAD_REVISION" ] || fail "the database is not at the Alembic head"
printf 'alembic head: %s\n' "$HEAD_REVISION"

step "8. RAGFlow (with ragflow-tei), api, worker, Caddy"
compose --profile public up -d ragflow api worker caddy || fail "docker compose up"

step "9. checks"
API_URL="http://127.0.0.1:${API_PORT:-8000}"
deadline=$((SECONDS + TIMEOUT))
until curl -fsS -o /dev/null "$API_URL/api/v1/healthz"; do
  [ "$SECONDS" -lt "$deadline" ] || fail "/healthz did not answer within ${TIMEOUT}s"
  sleep 5
done
HEALTH="ok"
PUBLIC_HEALTH="not checked"
if [ -n "$PUBLIC_URL" ]; then
  curl -fsS -o /dev/null "$PUBLIC_URL/api/v1/healthz" || fail "/healthz over TLS on the public host"
  PUBLIC_HEALTH="ok"
fi
AUTH_MODE="$(curl -fsS "$API_URL/api/v1/auth/mode" |
  python3 -c 'import json, sys; print(json.load(sys.stdin).get("mode", ""))')"
[ "$AUTH_MODE" = "$EXPECT_AUTH_MODE" ] || fail "auth/mode is '$AUTH_MODE', expected '$EXPECT_AUTH_MODE'"
RUNNING="$(running)"
grep -qx ragflow-tei <<<"$RUNNING" || fail "ragflow-tei (the embedding service) is not running"
grep -qx ragflow <<<"$RUNNING" || fail "ragflow is not running"
deadline=$((SECONDS + 60))
until grep -q '"event":"worker.started"' <<<"$(since_start worker)"; do
  [ "$SECONDS" -lt "$deadline" ] || fail "no worker.started line from the worker"
  sleep 3
done
MAIL_WARNINGS="$(grep -c '"event":"worker.mail_not_configured"' <<<"$(since_start api worker)" || true)"
[ "$MAIL_WARNINGS" = 0 ] || fail "worker.mail_not_configured at startup (the mail key is missing)"
dataset_counts >"$WORK/counts.after" || fail "ask-spore datasets counts"
DATASETS="$(wc -l <"$WORK/counts.after" | tr -d ' ')"
if [ -s "$WORK/counts.before" ]; then
  if diff -u "$WORK/counts.before" "$WORK/counts.after" >"$WORK/counts.diff"; then
    COUNTS="equal to before the deploy"
  else
    cat "$WORK/counts.diff" >&2
    fail "RAGFlow's dataset counts changed during the deploy"
  fi
else
  COUNTS="recorded (no earlier figures)"
fi

step "10. summary"
printf 'commit:              %s\n' "$FULL_SHA"
printf 'deploy version:      %s\n' "$ASK_SPORE_DEPLOY_VERSION"
printf 'alembic head:        %s\n' "$HEAD_REVISION"
printf 'healthz (loopback):  %s\n' "$HEALTH"
printf 'healthz (public):    %s\n' "$PUBLIC_HEALTH"
printf 'auth mode:           %s\n' "$AUTH_MODE"
printf 'ragflow-tei:         running\n'
printf 'worker:              started; mail warnings: %s\n' "$MAIL_WARNINGS"
printf 'datasets:            %s, %s\n' "$DATASETS" "$COUNTS"
sed 's/^/  /' "$WORK/counts.after"
printf 'started at:          %s\n' "$STARTED"
printf '\ndeploy: done\n'
