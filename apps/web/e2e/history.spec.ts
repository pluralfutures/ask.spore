import { expect, test, type Route } from "@playwright/test";

// P1c-09: chat history completeness. Synthetic fixtures only (CLAUDE.md).
const CONVERSATION_ID = "11111111-1111-4111-8111-111111111111";
const QUESTION = "How did synthetic capacity change?";
const CUT_OFF_NOTE = "This answer was cut off at the length limit.";
const PARTIAL_NOTE = "This answer was stopped before it finished.";
const conversation = {
  id: CONVERSATION_ID,
  title: "Synthetic capacity",
  created_at: "2026-10-17T10:00:00Z",
  updated_at: "2026-10-17T10:00:00Z",
  expires_at: "2026-11-16T10:00:00Z",
};
const citation = {
  marker: 1,
  source_id: "33333333-3333-4333-8333-333333333333",
  chunk_id: "chunk-synthetic-1",
  page_or_slide: 4,
  excerpt: "Synthetic capacity grew by 12 percent in 2025.",
  publisher: "Synthetic Institute",
  title: "Synthetic Outlook 2026",
  published_on: "2026-03-01",
  canonical_url: "https://example.org/synthetic-outlook",
  type: "pdf",
};

function message(n: number, role: "user" | "assistant", content: string, flags = {}) {
  return {
    id: `44444444-4444-4444-8444-${String(n).padStart(12, "0")}`,
    role,
    content,
    mode: "corpus_only",
    created_at: "2026-10-17T10:01:00Z",
    unsupported: false,
    abstained: false,
    citations: role === "assistant" ? [citation] : [],
    truncated: false,
    partial: false,
    ...flags,
  };
}

async function signedIn(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    sessionStorage.setItem(
      "askspore.phase0.credentials",
      JSON.stringify({ token: "synthetic-token", email: "analyst@example.org" }),
    );
  });
  await page.route("**/api/v1/conversations", (route: Route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/auth/mode", (route: Route) =>
    route.fulfill({ json: { mode: "phase0" } }),
  );
}

test("a reloaded conversation shows the cut-off and stopped notes", async ({ page }) => {
  await signedIn(page);
  await page.route(`**/api/v1/conversations/${CONVERSATION_ID}`, (route: Route) =>
    route.fulfill({
      json: {
        ...conversation,
        messages: [
          message(1, "user", QUESTION),
          message(2, "assistant", "Capacity grew [1] and", { truncated: true }),
          message(3, "user", "And in 2024?"),
          message(4, "assistant", "It grew [1]", { partial: true }),
          message(5, "user", "And in 2023?"),
          message(6, "assistant", "It fell [1].", {}),
        ],
      },
    }),
  );

  await page.goto(`/c/${CONVERSATION_ID}`);

  const notes = page.getByTestId("answer-note");
  await expect(notes).toHaveText([CUT_OFF_NOTE, PARTIAL_NOTE]);
  await expect(page.getByText("Capacity grew")).toBeVisible();
  await expect(page.getByText("It grew")).toBeVisible();
  await expect(page.getByText("It fell")).toBeVisible();
});

test("stop ends the answer, and the kept partial answer replaces it", async ({ page }) => {
  await signedIn(page);
  let stored = false;
  let release: () => void = () => {};
  const released = new Promise<void>((resolve) => (release = resolve));
  await page.route(`**/api/v1/conversations/${CONVERSATION_ID}`, (route: Route) =>
    route.fulfill({
      json: {
        ...conversation,
        messages: stored
          ? [message(1, "user", QUESTION), message(2, "assistant", "Kept [1]", { partial: true })]
          : [],
      },
    }),
  );
  // The answer never arrives: the model is still working when the user stops it.
  await page.route("**/api/v1/conversations/*/messages", async (route: Route) => {
    await released;
    await route.abort().catch(() => undefined);
  });

  await page.goto(`/c/${CONVERSATION_ID}`);
  await page.getByLabel("Question").fill(QUESTION);
  await page.getByRole("button", { name: "Ask" }).click();
  const stop = page.getByRole("button", { name: "Stop" });
  await expect(stop).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask" })).toHaveCount(0);

  stored = true; // the server keeps the turn when it sees the closed stream
  await stop.click();

  await expect(page.getByTestId("answer-note")).toHaveText([PARTIAL_NOTE]);
  await expect(page.getByText("Kept")).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask" })).toBeVisible();
  release();
});
