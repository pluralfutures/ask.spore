import { expect, test, type Page, type Route } from "@playwright/test";

// P2B-04: the first conversation's title when the answer ends before the page has handled
// the conversation's first load. Synthetic fixtures only (CLAUDE.md).
const CONVERSATION_ID = "11111111-1111-4111-8111-111111111111";
const QUESTION = "How did synthetic capacity change?";
const base = {
  id: CONVERSATION_ID,
  created_at: "2026-10-17T10:00:00Z",
  updated_at: "2026-10-17T10:00:00Z",
  expires_at: "2026-11-16T10:00:00Z",
  workspace_id: "ws-alpha",
  workspace_name: "Alpha team",
  mode: "corpus_only",
  model: "eu-fast",
  model_display_name: "EU Fast",
  reasoning: false,
};
const messageBase = {
  mode: "corpus_only",
  created_at: "2026-10-17T10:01:00Z",
  unsupported: false,
  abstained: false,
  truncated: false,
  partial: false,
};

async function signedIn(page: Page) {
  await page.addInitScript(() => {
    sessionStorage.setItem(
      "askspore.phase0.credentials",
      JSON.stringify({ token: "synthetic-token", email: "analyst@example.org" }),
    );
  });
  await page.route("**/api/v1/auth/mode", (route: Route) =>
    route.fulfill({ json: { mode: "phase0" } }),
  );
}

test("the title shown is the server's even when the answer ends before the first load", async ({
  page,
}) => {
  await signedIn(page);
  let answered = false;
  let titled = false;
  let release: () => void = () => {};
  const firstLoadHeld = new Promise<void>((resolve) => (release = resolve));
  let loads = 0;

  // The first load is slow: its response, made before the question was answered, reaches
  // the page only after the answer has ended.
  await page.route(`**/api/v1/conversations/${CONVERSATION_ID}`, async (route: Route) => {
    loads += 1;
    const stale = loads === 1;
    if (stale) await firstLoadHeld;
    await route.fulfill({
      json: {
        ...base,
        title: stale ? null : titled ? QUESTION : null,
        messages:
          stale || !answered
            ? []
            : [
                { ...messageBase, id: "m1", role: "user", content: QUESTION, citations: [] },
                {
                  ...messageBase,
                  id: "m2",
                  role: "assistant",
                  content: "Synthetic capacity grew [1].",
                  citations: [],
                },
              ],
      },
    });
  });
  await page.route("**/api/v1/conversations", (route: Route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/conversations/*/messages", async (route: Route) => {
    answered = true;
    titled = true;
    const done = {
      message_id: "m2",
      unsupported: false,
      abstained: false,
      cached: true,
      tokens_in: 1,
      tokens_out: 1,
      model: "eu-fast",
      reasoning: false,
      truncated: false,
    };
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body:
        `event: token\ndata: ${JSON.stringify({ text: "Synthetic capacity grew [1]." })}\n\n` +
        `event: citations\ndata: ${JSON.stringify({ citations: [] })}\n\n` +
        `event: done\ndata: ${JSON.stringify(done)}\n\n`,
    });
    setTimeout(release, 200); // the slow first load lands after the answer ended
  });

  await page.goto(`/c/${CONVERSATION_ID}`);
  await page.getByLabel("Question").fill(QUESTION);
  await page.getByRole("button", { name: "Ask" }).click();

  await expect(page.getByRole("heading", { level: 1, name: QUESTION })).toBeVisible();
  await expect(page.getByRole("heading", { name: "New conversation" })).toHaveCount(0);
});
