import { expect, test } from "@playwright/test";

import { FakeApi } from "./fakeApi";

// P2A-L1, P2A-L2: the Legal link is the last thing on every page, and /legal and its three
// documents are plain files outside the app (no sign-in, no consent redirect, no API call).
// The dev server mirrors the Caddyfile's routes as if ASKSPORE_LEGAL=published.

test("the legal pages are served without sign-in, a script or an API call", async ({ page }) => {
  const api = new FakeApi({ workspaces: [], models: [], consentPending: true });
  await api.install(page);
  const apiCalls: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) apiCalls.push(request.url());
  });

  const response = await page.goto("/legal");
  expect(response?.status()).toBe(200);
  for (const [name, path, heading] of [
    ["Privacy notice", "/legal/privacy", "Privacy notice"],
    ["AI transparency note", "/legal/ai", "AI transparency note"],
    ["Terms of Use", "/legal/terms", "Terms of Use"],
  ]) {
    await page.goto("/legal");
    await expect(page.getByRole("heading", { level: 1, name: "Legal" })).toBeVisible();
    await expect(page.getByRole("link", { name })).toHaveAttribute("href", path);
    const document = await page.request.get(path);
    expect(document.status(), path).toBe(200);
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await expect(page.locator("script")).toHaveCount(0);
    await expect(page.locator("#root")).toHaveCount(0);
  }
  expect(apiCalls).toEqual([]);
  expect(api.accepted).toEqual([]);
});

test("the files' own names are not served", async ({ request }) => {
  for (const path of [
    "/legal/index.html",
    "/legal/privacy.html",
    "/legal/ai.html",
    "/legal/terms.html",
  ]) {
    expect((await request.get(path)).status(), path).toBe(404);
  }
});
