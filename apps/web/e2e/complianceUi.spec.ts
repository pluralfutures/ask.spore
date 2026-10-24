import { expect, test, type Page } from "@playwright/test";

import * as F from "./scenarios/fixtures";
import { openScenario } from "./scenarios/open";
import {
  LONG_CONVERSATION,
  SCENARIOS,
  VIEWPORTS,
  askFirstQuestion,
  type Scenario,
} from "./scenarios/scenarios";

// UX-03: the binding compliance UI of design/specs/ux-refresh-spec.md. Each element keeps its
// wording and its place in the flow through the UX refresh; the strings below are the
// contract, so a change here needs the owner's approval as a wording change, separately from
// any visual change. Synthetic data only (CLAUDE.md).

test.use({ viewport: VIEWPORTS.desktop, locale: "en-GB", timezoneId: "UTC" });

const AI_NOTICE = "AI-generated, verify against cited sources.";
const SEARCHING = "Searching your research package…";
const EXTERNAL_NOTE = "This model is served outside the EU.";
const SPEND_CAP = "This month's budget for models served outside the EU has been used up.";
const PARTIAL_NOTE = "This answer was stopped before it finished.";
const CUT_OFF_NOTE = "This answer was cut off at the length limit.";
const FAILOVER_EXTERNAL =
  "This conversation's model was unavailable, so a backup model served outside the EU " +
  "answered, as your organisation allows.";
const SUPERSEDED_NOTE = "A newer version of this source has replaced the one this answer quoted.";
const WITHDRAWN_NOTE =
  "This source has been withdrawn from the research package since this answer.";
const EXCERPT_REMOVED = "The quoted passage was removed because the source was withdrawn.";
const NO_HISTORY_NOTE =
  "Your organisation keeps no chat history: each answer is deleted when it ends, and a " +
  "follow-up question starts afresh, without the earlier questions.";

function scenario(name: string): Scenario {
  const found = SCENARIOS.find((s) => s.name === name);
  if (!found) throw new Error(`no scenario ${name}`);
  return found;
}

async function open(page: Page, name: string, url?: string) {
  const base = scenario(name);
  return openScenario(page, url ? { ...base, url, act: undefined } : base);
}

test.describe("1. consent gate", () => {
  const gated = ["/", "/new", "/admin", `/c/${LONG_CONVERSATION}`, `/w/${F.WS_MARKETS.id}/files`];
  for (const url of gated) {
    test(`replaces ${url} until the notice is accepted`, async ({ page }) => {
      await openScenario(page, {
        name: "gate",
        url,
        options: { consentPending: true, role: "tenant_admin" },
      });
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Use and privacy notice");
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
      await expect(page.getByLabel("Question")).toHaveCount(0);
      await expect(page.getByRole("link")).toHaveCount(0); // no way round the gate
    });
  }

  test("shows the summary, the full notice and the acceptance, in that order", async ({ page }) => {
    await open(page, "05-consent-first");
    const main = page.getByRole("main");
    await expect(
      main.getByText("Please read and accept the notice before your first conversation."),
    ).toBeVisible();
    const summary = main.getByRole("region", { name: "In short" });
    const full = main.getByRole("region", { name: "Full notice" });
    await expect(summary).toContainText("Your questions and answers are kept for at most 30 days");
    await expect(full).toContainText("Synthetic paragraph on rights and contacts.");
    const box = main.getByRole("checkbox", { name: "I have read the notice (v1) and accept it." });
    const accept = main.getByRole("button", { name: "Accept and continue" });
    await expect(accept).toBeDisabled();
    const order = await main.evaluate((el) =>
      [...el.querySelectorAll("section, input[type=checkbox], button")].map(
        (n) => n.getAttribute("aria-labelledby") ?? n.tagName,
      ),
    );
    expect(order).toEqual(["consent-summary", "consent-full", "INPUT", "BUTTON"]);
    await box.check();
    await accept.click();
    await expect(page.getByRole("heading", { name: "Conversations" })).toBeVisible();
  });

  test("says when the notice has changed", async ({ page }) => {
    await open(page, "05b-consent-changed");
    await expect(
      page.getByText(
        "The notice has changed since you last accepted it. Please read and accept the new " +
          "version to continue.",
      ),
    ).toBeVisible();
    await expect(page.getByLabel("I have read the notice (v2) and accept it.")).toBeVisible();
  });

  test("says when the notice could not be loaded", async ({ page }) => {
    await open(page, "05c-consent-error");
    await expect(page.getByText("The notice could not be loaded.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Accept and continue" })).toHaveCount(0);
  });

  test("leaves the internal consoles reachable (P1b-10)", async ({ page }) => {
    await openScenario(page, {
      name: "console",
      url: "/operator",
      options: { consentPending: true, operator: true },
    });
    await expect(page.getByRole("heading", { name: "Operator console" })).toBeVisible();
  });
});

test.describe("2. AI transparency notice and answer labels", () => {
  const pages: [string, string?][] = [
    ["02-signin-email"],
    ["05-consent-first"],
    ["06-conversations"],
    ["07-start-panel-single"],
    ["08b-chat-answer"],
    ["10-files"],
    ["11-tenant-admin"],
    ["12-operator-console"],
    ["15-content-register"],
  ];
  for (const [name] of pages) {
    test(`is the first element of the page: ${name}`, async ({ page }) => {
      await open(page, name);
      const first = page.locator("#root > div > :first-child");
      await expect(first).toHaveRole("note");
      await expect(first).toHaveText(AI_NOTICE);
      await expect(first).toBeInViewport();
    });
  }

  test("is still the first element at phone width", async ({ page }) => {
    await page.setViewportSize(VIEWPORTS.phone);
    await open(page, "08b-chat-answer");
    const first = page.locator("#root > div > :first-child");
    await expect(first).toHaveText(AI_NOTICE);
    await expect(first).toBeVisible();
  });

  test("answer labels stay with the answer they qualify", async ({ page }) => {
    await open(page, "09c-chat-notes-abstain-unsupported");
    await expect(page.getByTestId("nothing-found")).toContainText("Nothing relevant found");
    const answers = page.locator("main ol > li");
    await expect(answers.filter({ hasText: "Synthetic cocoa prices rose sharply" })).toContainText(
      "Unsupported answer: no citations to your sources",
    );
    await expect(
      answers.filter({ hasText: "The synthetic regional breakdown starts" }),
    ).toContainText(PARTIAL_NOTE);
    const exports = answers.filter({ hasText: "Synthetic exports rose by 3%" });
    await expect(exports).toContainText(CUT_OFF_NOTE);
    await expect(exports).toContainText(FAILOVER_EXTERNAL);
    await expect(page.getByRole("main").locator("header")).toContainText("General knowledge");
  });

  test("the searching label shows while the answer is pending", async ({ page }) => {
    await open(page, "08-chat-searching");
    await expect(page.getByText(SEARCHING)).toBeVisible();
  });

  test("external models are disclosed on the start panel", async ({ page }) => {
    await open(page, "07c-start-panel-external");
    await expect(page.getByLabel("Model").locator("option:checked")).toHaveText(
      "Synthetic External Large (served outside the EU)",
    );
    await expect(page.getByTestId("external-note")).toHaveText(EXTERNAL_NOTE);
  });

  test("the spend-cap fallback is announced in the conversation header", async ({ page }) => {
    await open(page, "08e-chat-spend-cap-notice");
    const notice = page.getByRole("main").locator("header").getByRole("status");
    await expect(notice).toContainText(SPEND_CAP);
  });
});

test.describe("3. citation provenance", () => {
  test("every source shows title, publisher, date and page or slide", async ({ page }) => {
    await open(page, "09-chat-long-answer-many-citations");
    const panel = page.getByRole("complementary", { name: "Citations" });
    await expect(panel.getByTestId("citation-1")).toContainText("[1] Synthetic Outlook 2021");
    await expect(panel.getByTestId("citation-1")).toContainText(
      "Synthetic Commission for Agricultural Statistics · 1 Feb 2026 · p. 4",
    );
    await expect(panel.getByTestId("citation-4")).toContainText(
      "Synthetic Development Bank · 1 May 2026 · slide 7",
    );
    await expect(panel.getByTestId("citation-11")).toContainText("undated");
    await expect(
      panel.getByTestId("citation-1").getByRole("link", { name: "View at source" }),
    ).toHaveAttribute("href", "https://example.org/synthetic-outlook");
    await expect(panel.getByTestId("citation-11").getByRole("link")).toHaveCount(0);
    await expect(panel.getByTestId("citation-1")).toContainText("Synthetic excerpt 1:");
  });

  test("superseded and withdrawn sources say so", async ({ page }) => {
    await open(page, "09-chat-long-answer-many-citations");
    const panel = page.getByRole("complementary", { name: "Citations" });
    await expect(panel.getByTestId("citation-status-6")).toHaveText("superseded");
    await expect(panel.getByTestId("citation-6")).toContainText(SUPERSEDED_NOTE);
    await expect(panel.getByTestId("citation-status-7")).toHaveText("withdrawn");
    await expect(panel.getByTestId("citation-7")).toContainText(WITHDRAWN_NOTE);
    await expect(panel.getByTestId("citation-no-excerpt-7")).toHaveText(EXCERPT_REMOVED);
  });

  test("markers keep their names and open their source", async ({ page }) => {
    await open(page, "08b-chat-answer");
    await page.getByRole("button", { name: "Citation 2" }).click();
    const panel = page.getByRole("complementary", { name: "Citations" });
    await expect(panel.getByTestId("citation-2")).toHaveAttribute("aria-current", "true");
  });

  // Known failures (UX audit, backlog Oct 23, 2026), fixed by UX-16; when they start to
  // pass, Playwright reports it and the `test.fail` marks come off.
  test("on desktop the selected source is scrolled into view", async ({ page }) => {
    test.fail(true, "UX-16: the panel grows the page instead of scrolling to the source");
    await open(page, "09-chat-long-answer-many-citations");
    const panel = page.getByRole("complementary", { name: "Citations" });
    await expect(panel.getByTestId("citation-9")).toBeInViewport({ timeout: 2_000 });
  });

  test("on a phone the opened source is in view in a long conversation", async ({ page }) => {
    test.fail(true, "UX-16: the panel opens below the thread and composer, off-screen");
    await page.setViewportSize(VIEWPORTS.phone);
    await open(page, "09-chat-long-answer-many-citations");
    const panel = page.getByRole("complementary", { name: "Citations" });
    await expect(panel.getByTestId("citation-9")).toBeInViewport({ timeout: 2_000 });
  });
});

test.describe("4. history and retention indicators", () => {
  test("every conversation in the list shows when it expires", async ({ page }) => {
    await open(page, "06-conversations");
    const rows = page
      .getByRole("main")
      .getByRole("listitem")
      .filter({ has: page.getByRole("button", { name: "Delete" }) });
    await expect(rows).toHaveCount(5);
    for (const [i, date] of [
      "18 Nov 2026",
      "15 Nov 2026",
      "10 Nov 2026",
      "2 Nov 2026",
      "25 Oct 2026",
    ].entries()) {
      await expect(rows.nth(i)).toContainText(`Expires ${date}`);
    }
  });

  test("a conversation can be deleted from the list, after a confirmation", async ({ page }) => {
    await open(page, "06-conversations");
    const deleted = page.waitForRequest(
      (r) => r.method() === "DELETE" && r.url().includes("/api/v1/conversations/"),
    );
    let asked = "";
    page.removeAllListeners("dialog");
    page.on("dialog", (dialog) => {
      asked = dialog.message();
      void dialog.accept();
    });
    await page.getByRole("button", { name: "Delete" }).first().click();
    await deleted;
    expect(asked).toBe("Delete this conversation permanently?");
  });

  test("the conversation header shows when it expires", async ({ page }) => {
    await open(page, "08b-chat-answer");
    await expect(page.getByRole("main").locator("header")).toContainText("Expires 18 Nov 2026");
  });

  test("a no-history tenant is told so in the chat", async ({ page }) => {
    await open(page, "08f-chat-no-history");
    await expect(page.getByTestId("no-history")).toHaveText(NO_HISTORY_NOTE);
  });

  test("tenant admin retention keeps its explanation, summary and 30-day cap", async ({ page }) => {
    await open(page, "11-tenant-admin");
    const section = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Chat history retention" }),
    });
    await expect(section).toContainText(
      "Conversations are deleted after this many days, at most 30. Shortening it also " +
        "removes existing conversations older than the new limit. 0 keeps no history: each " +
        "conversation is deleted as soon as its answer ends.",
    );
    await expect(section.getByTestId("retention-summary")).toHaveText(
      "Conversations are deleted 30 days after they start.",
    );
    await expect(section.getByLabel("Days")).toHaveAttribute("max", "30");
  });
});

test.describe("5. feedback", () => {
  test("every stored answer has Helpful and Not helpful", async ({ page }) => {
    await open(page, "08b-chat-answer");
    const helpful = page.getByRole("button", { name: "Helpful", exact: true });
    await expect(helpful).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByRole("button", { name: "Not helpful" })).toBeVisible();
    await helpful.click();
    await expect(helpful).toHaveAttribute("aria-pressed", "true");
  });

  test("a 'nothing relevant found' answer has feedback too", async ({ page }) => {
    await open(page, "09c-chat-notes-abstain-unsupported");
    const nothing = page.getByTestId("nothing-found");
    await expect(nothing.getByRole("button", { name: "Helpful", exact: true })).toBeVisible();
    await expect(nothing.getByRole("button", { name: "Not helpful" })).toBeVisible();
  });

  test("a failed rating says so", async ({ page }) => {
    await openScenario(page, { ...scenario("08b-chat-answer"), options: { feedbackFails: true } });
    await page.getByRole("button", { name: "Helpful", exact: true }).click();
    await expect(page.getByText("Feedback not saved")).toBeVisible();
  });

  test("no-history turns have no feedback (nothing is stored to rate)", async ({ page }) => {
    await openScenario(page, { name: "no-history", url: "/new", options: { noHistory: true } });
    await askFirstQuestion(page);
    await expect(page.getByText("Synthetic capacity grew by 12%")).toBeVisible();
    await expect(page.getByRole("button", { name: "Helpful", exact: true })).toHaveCount(0);
  });
});
