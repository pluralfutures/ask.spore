import { expect, test } from "@playwright/test";

import { FakeApi } from "./fakeApi";

// P2A-11: security.txt and the disclosure page are served as plain files, outside the app:
// no sign-in, no consent redirect, no API call. The fake API is set up with the consent
// notice pending and no signed-in user, so the app would gate both if it ever served them.
// The dev server mirrors the Caddyfile's routes (vite.config.ts, publicPages).

const DAY_MS = 24 * 60 * 60 * 1000;

function fields(text: string): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const match = /^([A-Za-z-]+):\s*(\S.*)$/.exec(line);
    expect(match, `not a field line: ${line}`).not.toBeNull();
    const [, name, value] = match!;
    found.set(name.toLowerCase(), [...(found.get(name.toLowerCase()) ?? []), value]);
  }
  return found;
}

test("security.txt is served as text without sign-in and expires within a year", async ({
  page,
}) => {
  const api = new FakeApi({ workspaces: [], models: [], consentPending: true });
  await api.install(page);
  const apiCalls: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) apiCalls.push(request.url());
  });

  const response = await page.goto("/.well-known/security.txt");
  expect(response?.status()).toBe(200);
  expect(response?.headers()["content-type"]).toMatch(/^text\/plain/);
  expect(new URL(page.url()).pathname).toBe("/.well-known/security.txt");

  const parsed = fields(await response!.text());
  expect(parsed.get("contact")?.length).toBeGreaterThan(0);
  for (const contact of parsed.get("contact") ?? []) expect(contact).toMatch(/^(mailto|https):/);
  expect(parsed.get("expires")).toHaveLength(1);
  const expires = Date.parse(parsed.get("expires")![0]);
  expect(expires).toBeGreaterThan(Date.now());
  expect(expires - Date.now()).toBeLessThanOrEqual(365 * DAY_MS);
  expect(parsed.get("policy")?.[0]).toMatch(/\/security-disclosure$/);
  expect(apiCalls).toEqual([]);
});

test("the disclosure page is served without sign-in or a consent redirect", async ({ page }) => {
  const api = new FakeApi({ workspaces: [], models: [], consentPending: true });
  await api.install(page);
  const apiCalls: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) apiCalls.push(request.url());
  });

  const response = await page.goto("/security-disclosure");
  expect(response?.status()).toBe(200);
  await expect(
    page.getByRole("heading", { name: "Reporting a security vulnerability" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "/.well-known/security.txt" })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/security-disclosure");
  // Neither the consent notice nor the sign-in screen: the app never loaded.
  await expect(page.getByRole("button", { name: "Accept and continue" })).toHaveCount(0);
  await expect(page.locator("#root")).toHaveCount(0);
  await expect(page.locator("script")).toHaveCount(0);
  expect(apiCalls).toEqual([]);
  expect(api.accepted).toEqual([]);
});

test("the unpublished trust page and the files' own names are not served", async ({ request }) => {
  for (const path of ["/trust", "/trust.html", "/security-disclosure.html"]) {
    expect((await request.get(path)).status(), path).toBe(404);
  }
});
