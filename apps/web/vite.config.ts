import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import type { Connect, Plugin } from "vite";
import { defineConfig } from "vitest/config";

// P2A-11: the public pages' addresses, as infra/caddy/Caddyfile serves them in production
// (outside the app, its sign-in and its consent gate), mirrored here so the dev server and
// the Playwright check see the same routes. The trust page stays unpublished (404); the legal
// pages (P2A-L2) are served as if ASKSPORE_LEGAL=published, so the footer link can be checked.
const PUBLIC_PAGES: Record<string, string> = {
  "/security-disclosure": "/security-disclosure.html",
  "/legal": "/legal/index.html",
  "/legal/": "/legal/index.html",
  "/legal/privacy": "/legal/privacy.html",
  "/legal/ai": "/legal/ai.html",
  "/legal/terms": "/legal/terms.html",
};
const NOT_SERVED = new Set([
  "/security-disclosure.html",
  "/trust",
  "/trust.html",
  "/legal/index.html",
  "/legal/privacy.html",
  "/legal/ai.html",
  "/legal/terms.html",
]);

const publicPages: Connect.NextHandleFunction = (req, res, next) => {
  const path = (req.url ?? "").split("?", 1)[0];
  if (NOT_SERVED.has(path)) {
    res.statusCode = 404;
    res.end();
    return;
  }
  const file = PUBLIC_PAGES[path];
  if (file) req.url = file;
  next();
};

function publicPagesPlugin(): Plugin {
  return {
    name: "askspore-public-pages",
    configureServer(server) {
      server.middlewares.use(publicPages);
    },
    configurePreviewServer(server) {
      server.middlewares.use(publicPages);
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), publicPagesPlugin()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    proxy: {
      // The browser calls /api/v1 on the web origin; Vite forwards it to the API.
      "/api": process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}", "scripts/**/*.test.mjs"],
  },
});
