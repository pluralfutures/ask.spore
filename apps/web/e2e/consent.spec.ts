import { expect, test } from "@playwright/test";

import { FakeApi } from "./fakeApi";

// P1b-10: the first-login consent gate, against the fake API.
test("shows the notice before the first conversation and records the acceptance", async ({
  page,
}) => {
  const api = new FakeApi({ workspaces: [], models: [], consentPending: true });
  await api.install(page);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Synthetic Notice" })).toBeVisible();
  await expect(page.getByText("Synthetic plain-language summary.")).toBeVisible();
  await expect(page.getByText("Synthetic full wording of the notice.")).toBeVisible();
  await expect(page.getByLabel("Question")).toHaveCount(0);
  const accept = page.getByRole("button", { name: "Accept and continue" });
  await expect(accept).toBeDisabled();

  await page.getByLabel(/I have read the notice/).check();
  await accept.click();
  await expect(page.getByRole("heading", { name: /^Welcome to / })).toBeVisible();
  expect(api.accepted).toEqual([{ version: "v1" }]);
});
