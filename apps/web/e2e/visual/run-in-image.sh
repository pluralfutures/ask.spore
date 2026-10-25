#!/bin/sh
# UX-05: runs the visual suite (playwright.visual.config.ts) inside the pinned Playwright
# image, the same image the CI job uses, so snapshots do not depend on the machine's fonts
# or browser build. Extra arguments go to Playwright, for example --update-snapshots or
# -g "08c". Needs Docker. Packages are installed inside the container, in a volume that
# hides the host's node_modules, so a macOS checkout works too.
set -eu

IMAGE="mcr.microsoft.com/playwright:v1.63.0-noble@sha256:eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27"
ROOT="$(git rev-parse --show-toplevel)"

# A proxy and an extra CA bundle (as behind a TLS-inspecting proxy) are passed through.
EXTRA_CA=""
if [ -n "${NODE_EXTRA_CA_CERTS:-}" ]; then
  EXTRA_CA="-v $NODE_EXTRA_CA_CERTS:/etc/extra-ca.crt:ro -e NODE_EXTRA_CA_CERTS=/etc/extra-ca.crt"
fi

# shellcheck disable=SC2086
exec docker run --rm --init --ipc=host --network host $EXTRA_CA \
  -e CI= -e HTTPS_PROXY -e HTTP_PROXY -e NO_PROXY -e https_proxy -e http_proxy -e no_proxy \
  -v "$ROOT:/work" -v /work/apps/web/node_modules \
  -w /work/apps/web "$IMAGE" \
  sh -c 'corepack enable >/dev/null && pnpm install --frozen-lockfile --reporter=silent --store-dir /tmp/pnpm-store \
    && pnpm exec playwright test --config playwright.visual.config.ts "$@"' sh "$@"
