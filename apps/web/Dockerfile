# Production build (Phase 1a release, one host). Builds dist/; the one-shot `web-build`
# service copies it into the `web_dist` volume, which Caddy serves read-only.
FROM node:22.23.3-bookworm-slim@sha256:3ed98443660ff48413b5af19ecefce3b9d50845a901a43420d47cc63a9fddbe9 AS build
RUN npm install -g pnpm@10.28.0
WORKDIR /srv/web
COPY package.json pnpm-lock.yaml .npmrc ./
RUN pnpm install --frozen-lockfile
COPY index.html vite.config.ts tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY src ./src
# P2A-11: the public files (security.txt, the disclosure page) are copied to dist/ as they are.
COPY public ./public
RUN pnpm build

FROM busybox:1.37.0@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e
COPY --from=build /srv/web/dist /dist
# Replace the volume's contents so files from an earlier build do not linger.
CMD ["sh", "-c", "find /out -mindepth 1 -delete && cp -a /dist/. /out/"]
