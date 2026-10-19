import { expect, test } from "@playwright/test";

import { FakeApi } from "./fakeApi";

// P1a-13: tenant admin pages, against the fake API.
const WORKSPACES = [
  {
    id: "aaaaaaaa-0000-4000-8000-000000000001",
    slug: "team-alpha",
    name: "Synthetic Team Alpha",
    default_mode: "corpus_only",
    default_model: "eu-fast",
    default_reasoning: false,
  },
];
const MODELS = [
  {
    id: "eu-fast",
    display_name: "Synthetic EU Fast",
    external: false,
    reasoning_switch: true,
    default: true,
  },
];

test("a user cannot open the admin pages", async ({ page }) => {
  const api = new FakeApi({ workspaces: WORKSPACES, models: MODELS, role: "user" });
  await api.install(page);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "New conversation" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Administration" })).toHaveCount(0);
  await page.goto("/admin");
  await expect(page.getByText("Tenant admins only.")).toBeVisible();
  expect(api.adminCalls).toEqual([]);
});

test("an admin saves the instructions as a new version", async ({ page }) => {
  const api = new FakeApi({ workspaces: WORKSPACES, models: MODELS, role: "tenant_admin" });
  await api.install(page);
  await page.goto("/");
  await page.getByRole("link", { name: "Administration" }).click();
  await expect(page.getByTestId("user-analyst@example.org")).toContainText("sign-in link");

  const instructions = page.getByLabel("Additional instructions");
  const save = page.getByRole("button", { name: "Save as new version" });
  for (const text of ["Synthetic first instructions.", "Synthetic second instructions."]) {
    await instructions.fill(text);
    await save.click();
    await expect(save).toBeDisabled();
  }
  await page.getByText("Version history (2)").click();
  await expect(page.getByTestId("version-2")).toContainText("Synthetic second instructions.");
  await expect(page.getByTestId("version-1")).toContainText("Synthetic first instructions.");
  await expect(instructions).toHaveValue("Synthetic second instructions.");

  await page.getByLabel("Days").fill("31");
  await page.getByRole("button", { name: "Save retention" }).click();
  await expect(page.getByText("Retention cannot exceed 30 days.")).toBeVisible();
  expect(api.adminCalls.filter((c) => c.path === "/admin/settings/retention")).toEqual([]);
});
