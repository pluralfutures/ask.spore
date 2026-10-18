import { expect, test, type Route } from "@playwright/test";

// Synthetic fixtures only (CLAUDE.md): no real documents or queries.
const CONVERSATION_ID = "11111111-1111-4111-8111-111111111111";
const MESSAGE_ID = "22222222-2222-4222-8222-222222222222";
const conversation = {
  id: CONVERSATION_ID,
  title: null,
  created_at: "2026-10-17T10:00:00Z",
  updated_at: "2026-10-17T10:00:00Z",
  expires_at: "2026-11-16T10:00:00Z",
  messages: [],
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

function sse(events: [string, unknown][]): string {
  return events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

test("asks a question, streams the answer and opens its citation", async ({ page }) => {
  const asked: unknown[] = [];
  await page.addInitScript(() => {
    sessionStorage.setItem(
      "askspore.phase0.credentials",
      JSON.stringify({ token: "synthetic-token", email: "analyst@example.org" }),
    );
  });
  await page.route("**/api/v1/conversations/*/messages", async (route: Route) => {
    asked.push(route.request().postDataJSON());
    expect(route.request().headers()["authorization"]).toBe("Bearer synthetic-token");
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body: sse([
        ["token", { text: "Capacity grew by 12% " }],
        ["token", { text: "in 2025 [1]." }],
        ["citations", { citations: [citation] }],
        [
          "done",
          {
            message_id: MESSAGE_ID,
            unsupported: false,
            abstained: false,
            cached: false,
            tokens_in: 900,
            tokens_out: 12,
          },
        ],
      ]),
    });
  });
  // Until the answer is persisted the conversation is empty; afterwards it holds it.
  let persisted = false;
  await page.route(`**/api/v1/conversations/${CONVERSATION_ID}`, async (route: Route) => {
    const messages = persisted
      ? [
          {
            id: "44444444-4444-4444-8444-444444444444",
            role: "user",
            content: "How did synthetic capacity change?",
            mode: "corpus_only",
            created_at: "2026-10-17T10:01:00Z",
            unsupported: false,
            abstained: false,
            citations: [],
          },
          {
            id: MESSAGE_ID,
            role: "assistant",
            content: "Capacity grew by 12% in 2025 [1].",
            mode: "corpus_only",
            created_at: "2026-10-17T10:01:02Z",
            unsupported: false,
            abstained: false,
            citations: [citation],
          },
        ]
      : [];
    await route.fulfill({ json: { ...conversation, messages } });
  });
  await page.route("**/api/v1/conversations", (route: Route) => route.fulfill({ json: [] }));

  await page.goto(`/c/${CONVERSATION_ID}`);
  await expect(page.getByRole("note")).toHaveText("AI-generated, verify against cited sources.");
  await expect(page.getByText("Expires 16 Nov 2026")).toBeVisible();

  await page.getByLabel("Question").fill("How did synthetic capacity change?");
  persisted = true;
  await page.getByRole("button", { name: "Ask" }).click();

  await expect(page.getByText("Capacity grew by 12% in 2025")).toBeVisible();
  expect(asked).toEqual([{ question: "How did synthetic capacity change?" }]);
  await expect(page.getByTestId("unsupported")).toHaveCount(0);

  await page.getByRole("button", { name: "Citation 1" }).click();
  const panel = page.getByRole("complementary", { name: "Citations" });
  await expect(panel.getByTestId("citation-1")).toContainText("Synthetic Outlook 2026");
  await expect(panel).toContainText("Synthetic Institute · 1 Mar 2026 · p. 4");
  await expect(panel).toContainText("Synthetic capacity grew by 12 percent in 2025.");
  await expect(panel.getByRole("link", { name: "View at source" })).toHaveAttribute(
    "href",
    "https://example.org/synthetic-outlook",
  );
});
