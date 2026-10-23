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

  const workspace = page.getByTestId("workspace-team-alpha");
  const instructions = page.getByLabel("Additional instructions");
  const save = page.getByRole("button", { name: "Save as new version" });
  const texts = ["Synthetic first instructions.", "Synthetic second instructions."];
  for (const [index, text] of texts.entries()) {
    await instructions.fill(text);
    await save.click();
    // Wait for the end of the save, which the editor shows once the history is reloaded
    // and the draft settled (P1c-11). The history count and a disabled button are not
    // enough: both also hold while the save is still finishing (P1b-13 f, PR #35).
    await expect(workspace.getByRole("status")).toHaveText(`Saved as version ${index + 1}.`);
    await expect(page.getByText(`Version history (${index + 1})`)).toBeVisible();
    await expect(save).toBeDisabled();
    await expect(instructions).toHaveValue(text);
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

test("an admin resends an invitation, removes a user, and sees a taken address", async ({
  page,
}) => {
  const api = new FakeApi({ workspaces: WORKSPACES, models: MODELS, role: "tenant_admin" });
  await api.install(page);
  await page.goto("/admin");

  // P1c-07: only the invited user offers a resend; nobody can remove themselves.
  const invited = page.getByTestId("user-invited@example.org");
  const member = page.getByTestId("user-member@example.org");
  const self = page.getByTestId("user-analyst@example.org");
  await expect(member.getByRole("button", { name: "Resend invitation" })).toHaveCount(0);
  await expect(self.getByRole("button", { name: "Remove" })).toHaveCount(0);
  await invited.getByRole("button", { name: "Resend invitation" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Invitation sent again to invited@example.org.",
  );
  expect(api.resent).toEqual(["55555555-5555-4555-8555-555555555556"]);

  // Removal asks first; cancelling sends nothing.
  await member.getByRole("button", { name: "Remove" }).click();
  await member.getByRole("button", { name: "Cancel" }).click();
  expect(api.adminCalls.filter((c) => c.method === "DELETE")).toEqual([]);
  await member.getByRole("button", { name: "Remove" }).click();
  await member.getByRole("button", { name: "Remove member@example.org" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "member@example.org was removed with their conversations.",
  );
  await expect(member).toHaveCount(0);
  expect(api.adminCalls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual([
    "/admin/users/55555555-5555-4555-8555-555555555557",
  ]);

  // The 409 email_taken reads as a sentence, not a status code.
  await page.getByLabel("Email", { exact: true }).fill("invited@example.org");
  await page.getByLabel("Name", { exact: true }).fill("Synthetic Again");
  await page.getByRole("button", { name: "Invite" }).click();
  await expect(page.getByText("That address already has an account.")).toBeVisible();
});
