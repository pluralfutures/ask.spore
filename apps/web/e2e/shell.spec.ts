import { expect, test, type Page } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS, type Scenario } from "./scenarios/scenarios";

// UX-10 (design/specs/ux-refresh-spec.md): the app shell. Under the AI notice (UX-03 keeps
// it the first element), a skip link, the top bar with the product, the tenant, a nav that
// follows the user's roles and the user menu, then the page's one <main>.
test.use({ viewport: VIEWPORTS.desktop, locale: "en-GB", timezoneId: "UTC" });

const scenario = (name: string) => SCENARIOS.find((s) => s.name === name)!;
const nav = (page: Page) => page.getByRole("navigation", { name: "Main" });
const navLinks = (page: Page) => nav(page).getByRole("link").allTextContents();

for (const s of SCENARIOS) {
  test(`one main landmark: ${s.name}`, async ({ page }) => {
    await openScenario(page, s);
    await expect(page.getByRole("main")).toHaveCount(1);
    await expect(page.locator("#root > [role=banner] > :first-child")).toHaveRole("note");
    // P2A-L1: the Legal link is the last landmark, after the page.
    const footer = page.getByRole("contentinfo");
    await expect(footer).toHaveCount(1);
    await expect(footer.getByRole("link")).toHaveCount(1);
    await expect(footer.getByRole("link", { name: "Legal" })).toHaveAttribute("href", "/legal");
    await expect(page.locator("#root > :last-child")).toHaveRole("contentinfo");
  });
}

test("a user sees the product, the tenant and Home only", async ({ page }) => {
  await openScenario(page, scenario("06-conversations"));
  await expect(page.getByRole("link", { name: "Mycelium SporeBot" })).toBeVisible();
  await expect(page.getByTestId("tenant-name")).toHaveText("Synthetic Client");
  expect(await navLinks(page)).toEqual(["Home"]);
  await expect(nav(page).getByRole("link", { name: "Home" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("an admin and operator also see Administration and the operator console", async ({ page }) => {
  await openScenario(page, scenario("06b-conversations-admin-operator"));
  expect(await navLinks(page)).toEqual(["Home", "Administration", "Operator console"]);
  await nav(page).getByRole("link", { name: "Administration" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Administration");
  await expect(nav(page).getByRole("link", { name: "Administration" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("content staff see the content console", async ({ page }) => {
  await openScenario(page, scenario("15-content-register"));
  expect(await navLinks(page)).toContain("Content console");
  await expect(nav(page).getByRole("link", { name: "Content console" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("while the notice waits, the consoles stay but no gated page is linked", async ({ page }) => {
  const console: Scenario = {
    name: "console",
    url: "/operator",
    options: { consentPending: true, operator: true, role: "tenant_admin" },
  };
  await openScenario(page, console);
  expect(await navLinks(page)).toEqual(["Operator console"]);
  await expect(page.getByRole("link", { name: "Mycelium SporeBot" })).toHaveCount(0);
});

test("the skip link is the first stop and moves focus to the page", async ({ page }) => {
  await openScenario(page, scenario("11-tenant-admin"));
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "← Conversations" })).toBeFocused();
});

test("sign-out is in the user menu and signs out as before", async ({ page }) => {
  const api = await openScenario(page, {
    name: "oidc",
    url: "/",
    options: { mode: "oidc", signedIn: true },
  });
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
  await page.getByRole("button", { name: "Account: Synthetic Analyst" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page.getByLabel("Email")).toBeVisible();
  expect(api.signedOut).toBe(true);
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
});

test("the top bar fits a phone", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.phone);
  await openScenario(page, scenario("06b-conversations-admin-operator"));
  await expect(nav(page)).toBeVisible();
  const width = (await page.evaluate("document.documentElement.scrollWidth")) as number;
  expect(width).toBeLessThanOrEqual(VIEWPORTS.phone.width);
});
