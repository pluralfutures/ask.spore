# Production build (Phase 1a release, one host). Builds dist/; the one-shot `web-build`
# service copies it into the `web_dist` volume, which Caddy serves read-only.
FROM node:22.23.3-bookworm-slim AS build
RUN npm install -g pnpm@10.28.0
WORKDIR /srv/web
COPY package.json pnpm-lock.yaml .npmrc ./
RUN pnpm install --frozen-lockfile
COPY index.html vite.config.ts tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY src ./src
RUN pnpm build

FROM busybox:1.37.0
COPY --from=build /srv/web/dist /dist
# Replace the volume's contents so files from an earlier build do not linger.
CMD ["sh", "-c", "find /out -mindepth 1 -delete && cp -a /dist/. /out/"]
