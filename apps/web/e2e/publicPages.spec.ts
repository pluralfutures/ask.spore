import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// P2B-02: the static public pages look like the app (header, card on the canvas, Lato) and
// stay plain files: same-origin resources only, no script, no sideways page scroll.
const PAGES = ["/legal", "/legal/privacy", "/legal/ai", "/legal/terms", "/security-disclosure"];
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"];

for (const path of PAGES) {
  test(`${path}: app header and footer, Lato, passes axe`, async ({ page }) => {
    const origins = new Set<string>();
    page.on("request", (request) => origins.add(new URL(request.url()).origin));
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(path);
    await page.evaluate("document.fonts.ready.then(() => undefined)");

    const banner = page.getByRole("banner");
    await expect(banner.getByRole("link", { name: "Mycelium SporeBot" })).toHaveAttribute(
      "href",
      "/",
    );
    await expect(page.getByRole("contentinfo").getByRole("link", { name: "Legal" })).toBeVisible();
    await expect(page.locator("script")).toHaveCount(0);

    const style = await page.evaluate(() => {
      const heading = getComputedStyle(document.querySelector("h1")!);
      return {
        family: heading.fontFamily,
        canvas: getComputedStyle(document.body).backgroundColor,
        loaded: document.fonts.check("700 16px Lato"),
        brand: document.fonts.check("700 16px Poppins"),
      };
    });
    expect(style.family).toContain("Lato");
    expect(style.canvas).toBe("rgb(246, 247, 249)");
    expect(style.loaded).toBe(true);
    expect(style.brand).toBe(true);
    expect([...origins]).toEqual([new URL(page.url()).origin]);

    const result = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target)}`)).toEqual([]);
  });

  test(`${path}: no sideways page scroll at 390 px`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto(path);
    expect(await page.evaluate("document.documentElement.scrollWidth")).toBeLessThanOrEqual(390);
  });
}

test("a wide privacy-notice table scrolls in its own region at 390 px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/legal/privacy");
  const region = page.getByRole("group", { name: "Table" }).first();
  await expect(region).toBeVisible();
  await region.focus();
  await expect(region).toBeFocused();
});
