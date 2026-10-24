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
        await expect(page.getByRole("heading", { level: 1 })).toHaveText("SporeBot");
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
