import { expect, test } from "@playwright/test";

import { openScenario } from "./scenarios/open";
import { SCENARIOS, VIEWPORTS } from "./scenarios/scenarios";

// UX-11 (design/specs/ux-refresh-spec.md): every sign-in page is one centred card in the
// page's main landmark, with the product name as its h1.
const SIGN_IN = SCENARIOS.filter((s) => /^0[1-3]/.test(s.name));

test("every sign-in state is covered", () => {
  expect(SIGN_IN.map((s) => s.name)).toEqual([
    "01-signin-token",
    "02-signin-email",
    "02b-signin-email-sso-failed",
    "02c-signin-email-sent",
    "02d-signin-sso-choice",
    "03-finish-sign-in",
    "03b-second-factor-setup",
    "03c-second-factor-code",
  ]);
});

for (const [width, viewport] of Object.entries(VIEWPORTS)) {
  test.describe(width, () => {
    test.use({ viewport, locale: "en-GB", timezoneId: "UTC" });
    for (const s of SIGN_IN) {
      test(`centred card: ${s.name}`, async ({ page }) => {
        await openScenario(page, s);
        const card = page.getByRole("main").getByTestId("auth-card");
        await expect(card).toHaveCount(1);
        await expect(page.getByRole("heading", { level: 1 })).toHaveText("Mycelium SporeBot");
        await expect(card.getByRole("heading", { level: 1 })).toHaveCount(1);
        const box = (await card.boundingBox())!;
        const centre = box.x + box.width / 2;
        expect(Math.abs(centre - viewport.width / 2)).toBeLessThanOrEqual(1);
        expect(box.width).toBeLessThanOrEqual(384);
        // A 16 px gutter on phone; the card never touches the edge.
        expect(box.x).toBeGreaterThanOrEqual(16);
      });
    }
  });
}

// UX-24 (owner approval, Oct 24, 2026): each step names itself in an h2 and in the tab
// title; moving to a later step puts focus on its heading.
const STEPS: Record<string, string> = {
  "01-signin-token": "Sign in",
  "02-signin-email": "Sign in",
  "02b-signin-email-sso-failed": "Sign in",
  "02c-signin-email-sent": "Check your email",
  "02d-signin-sso-choice": "Sign in",
  "03-finish-sign-in": "Finish signing in",
  "03b-second-factor-setup": "Set up your authenticator app",
  "03c-second-factor-code": "Enter your code",
};

test.describe("step headings", () => {
  test.use({ viewport: VIEWPORTS.desktop });

  for (const s of SIGN_IN) {
    test(`h2 and tab title: ${s.name}`, async ({ page }) => {
      await openScenario(page, s);
      const step = STEPS[s.name];
      await expect(page.getByRole("heading", { level: 2 })).toHaveText(step);
      await expect(page).toHaveTitle(`${step} – SporeBot`);
    });
  }

  test("the first step leaves focus alone; the next step focuses its heading", async ({ page }) => {
    await openScenario(
      page,
      SIGN_IN.find((s) => s.name === "02-signin-email")!,
    );
    await expect(page.getByRole("heading", { level: 2 })).not.toBeFocused();
    await page.getByLabel("Email").fill("someone@example.org");
    await page.getByRole("button", { name: "Continue" }).click();
    const sent = page.getByRole("heading", { level: 2, name: "Check your email" });
    await expect(sent).toBeFocused();
  });

  test("the code step focuses its heading after the link step", async ({ page }) => {
    const s = SIGN_IN.find((x) => x.name === "03c-second-factor-code")!;
    await openScenario(page, s);
    await expect(page.getByRole("heading", { level: 2, name: "Enter your code" })).toBeFocused();
  });
});

test.describe("second factor", () => {
  test.use({ viewport: VIEWPORTS.desktop });

  test("enrolment shows the QR code and the key; the code field is named", async ({ page }) => {
    await openScenario(
      page,
      SIGN_IN.find((s) => s.name === "03b-second-factor-setup")!,
    );
    await expect(
      page.getByRole("img", { name: "QR code for your authenticator app" }),
    ).toBeVisible();
    await expect(page.getByText("JBSW Y3DP EHPK 3PXP")).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Code" })).toBeVisible();
  });
});
