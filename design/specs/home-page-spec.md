# Home Page Build Spec

Oct 26, 2026 · Status: **approved by the owner on Oct 26, 2026 as its own phase** (open item 1 below), built HP-01 to HP-05 in order. All four open items were decided the same day: the wording table as proposed with "Ask" on the submit button, "Hide" remembered in the browser, and nothing to show the welcome again for now.

Source: the owner's choice of mock-up **D** ("Welcome (A) + question box (B) + recent (B)") on the design canvas https://claude.ai/artifact/TZUsymQSMPvcyDCh36QfVf (private to the owner until shared). Mock-ups A to C on the same canvas are the alternatives that were not chosen. After the owner's edits of Oct 26, 2026, D has no subtitle under the question heading and no example-question chips.

## Goal

Today a signed-in user lands on `/`, the conversation list (`pages/ConversationList.tsx`). Nothing there says what SporeBot is for or how to get a good answer, and asking a question means first going to `/new`. The new home page answers "what is this?" and "how do I use it?" and lets the user ask straight away. It shows, from top to bottom:

1. a **welcome card** that the user can hide;
2. a **question box**: the existing start form, moved onto the home page;
3. **recent conversations**: the three most recent, then an "All conversations" link to the full list.

Exit criteria (all must hold):

- `/` shows the three sections in that order for a user who has accepted the notice. The full list moves to `/conversations` and works as today.
- Starting a conversation from the home page sends the same request as `/new` today (`createBody`). It keeps every refusal, notice and no-history behaviour.
- Every element of the UX refresh's binding compliance list ([ux-refresh-spec.md](ux-refresh-spec.md#binding-compliance-ui)) is present on the pages it covers, and the UX-03 contract tests pass, extended as in HP-05.
- The visual, axe, overflow, keyboard and screen-reader suites pass with the new and moved scenarios. Nothing is added to the allow-lists.
- `pnpm lint`, `pnpm typecheck`, `pnpm test` and the Playwright suites pass.

## Not in this spec

Binding once approved. Ideas go in `backlog.md`; the first three are already there (HP spec lines).

- Example questions for each workspace (they were in mock-ups A to C and the owner removed them from D), and suggested questions generated from the sources (architecture §7.1).
- A "what this workspace knows" summary (document count, publishers, last updated) on the home page.
- A help page, a guided tour, or tips beyond the welcome card's three steps.
- Any change to the API, the database, the prompt, what is logged or what is sent to a model. Open item 3, option (b), would add an API change; it is out unless the owner picks it.
- Conversation search, rename or filters (backlog, UX audit line).

## What stays binding

The UX refresh's binding compliance list still applies in full. Where the home page touches it:

- **AI notice.** It stays the first element in `body`, above the top bar.
- **Consent gate.** `/` and `/conversations` are both gated until the notice is accepted. The welcome card is never shown on the gate or instead of it.
- **Start settings, kept even though mock-up D draws them without them.** The question box carries the whole `StartPanel`:
  - the workspace chooser (hidden for a single workspace);
  - the model chooser, or the read-only model when only one is enabled (UX-14);
  - the reasoning switch;
  - the external-model label suffix and the "This model is served outside the EU." notice;
  - the locked-settings rule: settings are fixed once the conversation starts.

  Mock-up D shows only Workspace and Reasoning, because it was drawn for a tenant with one model. It is not a decision to drop the model.
- **Start-flow notices.** The spend-cap fallback notice and the no-history behaviour (P1b-14) work from the home page exactly as from `/new`.
- **Retention.** Every conversation row, on the home page and on `/conversations`, shows "Expires {date}" and keeps its row menu with "Delete" behind the confirmation dialog. No text on the page may suggest that history is kept longer than 30 days (see the welcome wording, open item 2).
- **Dataset IDs.** The question box sends only the user's own choice (`createBody`: workspace ID, model, reasoning). Dataset and document IDs never come from the client (CLAUDE.md).

## Wording

New copy needs the owner's approval before it is built (open item 2). Mock-up D's text is corrected here in two places where it would be untrue for some tenants:

| Where | Mock-up D | Proposed | Why it differs |
|---|---|---|---|
| Welcome `h1` | Welcome to Mycelium SporeBot | same, using `ProductName` | — |
| Welcome lead | …SporeBot answers **only** from the sources in your workspace and cites every claim, so you can check it. | Ask research questions in plain language. SporeBot searches your workspace's sources and cites them, so you can check each claim. | A workspace whose default mode is "General knowledge" does not answer only from its sources. |
| Step 1 (only when the user has more than one workspace) | **Pick a workspace.** Each one covers a different set of sources. | same | With one workspace there is no chooser, so the step is left out and the others renumber. |
| Step 2 | **Ask a specific question.** Name a product, region or period for sharper answers. | same | — |
| Step 3 | **Check the citations.** Click a number to see the excerpt and its page. | **Check the citations.** Click a number to see the excerpt and where it comes from. | Pages are shown only when known; websites have none. |
| Welcome footer | Conversations are deleted after 30 days. SporeBot doesn't know anything outside your workspace's sources. | Conversations are deleted automatically, after 30 days at most. | A tenant may set a shorter retention, or 0 days. The second sentence is untrue in "General knowledge" mode. The API does not expose the tenant's retention to users, so the line cannot name the tenant's own figure without an API change. |
| Hide button | Hide | Hide (accessible name "Hide the welcome") | The visible word alone is ambiguous to a screen reader. |
| Question heading (`h2`) | What would you like to research? | same | — |
| Question placeholder | For example: Which plant-based proteins grew fastest on European menus in 2025? | Ask a question about this workspace's sources (today's text) | An example would differ by workspace and tenant. That is the example-questions feature, which is not in this spec. |
| Submit button (home page) | Ask | Ask (owner, Oct 26, 2026) | `/new` keeps "Start", so HP-01 changes nothing there. |
| Top-bar nav item | Home | Home | "Conversations" now names the `/conversations` page. |
| Recent heading | Recent conversations | same | — |
| Link under the list | All conversations | same | — |

## Work items

Build in this order. Each item is one PR, references its ID in commits (`HP-02: …`), and updates the reviewed visual and screen-reader snapshots it changes in the same PR.

**HP-01 Extract the start form (no visual change).**
- Move the form in `pages/NewConversation.tsx` into a reusable `StartForm` component (`components/StartForm.tsx`). It keeps everything the form has today: question textarea, `StartPanel`, refusal notice, submit button, the `useMutation` with its `navigate` to `/c/:id` carrying `StartState`, and the loading, error and no-workspace states.
- It takes props for what differs between pages: the heading level and text (`h1` "New conversation" on `/new`, `h2` "What would you like to research?" on the home page) and the submit label (open item 2).
- `NewConversation` renders `StartForm` inside its existing `StartPage`.
- The visual, axe and screen-reader diffs of `/new` must be zero.
- Tests: the existing `start.spec.ts` and `startPanel.spec.ts` pass unchanged. A vitest test renders `StartForm` with both heading props.

**HP-02 Move the full list to `/conversations`.**
- Add the route `/conversations`, rendering today's `ConversationList` page with its `PageHeader` "Conversations" and the **New conversation** button.
- The "Files behind each workspace" links move with it. The top bar has no Files item, and dropping these links would leave no way to reach `/w/:id/files` from the app.
- The "← Conversations" back links on the chat and start pages point to `/conversations`.
- Deleting the open conversation still goes to `/`.
- `/` keeps rendering the list until HP-04, so this PR changes no pixels on `/`.
- Tests: `/conversations` lists every conversation with "Expires" on each row. The back links lead there. The consent gate blocks `/conversations` (added to the gated list in `complianceUi.spec.ts`).

**HP-03 Welcome card.**
- `components/Welcome.tsx`: a `Card` with the `h1`, lead, steps (an ordered list, step 1 only when there is more than one workspace), footer line and the Hide button, with the wording approved under open item 2.
- Hide removes the card and moves focus to the question box's heading, so keyboard focus is not lost.
- How Hide is remembered is open item 3. For option (a), the recommendation:
  - one browser-storage key, `sporebot.welcome-hidden`, value `"1"`. No other data. *Changed in the HP-03 build, Oct 26, 2026:* the key was to include the user ID, but `/me` gives the web app no user ID and the email is personal data, so the key holds no identifier. Two people sharing one browser profile share the flag.
  - every read and write is wrapped in `try`/`catch`. If storage is unavailable or throws, the card shows and Hide works for the current page view only.
- Tests (vitest and Playwright):
  - the card shows on first visit and stays hidden after Hide and a reload;
  - with storage throwing, the card still shows, Hide still works and nothing errors;
  - step 1 is absent for a tenant with one workspace;
  - the key holds no data other than the flag;
  - the card is never shown on the consent gate (negative case).

**HP-04 Compose the home page at `/`.**
- `pages/Home.tsx` at `/`, replacing `ConversationList` there. It shows the welcome card (HP-03), the start form with the `h2` (HP-01), then "Recent conversations".
- "Recent conversations" is `ConversationLinks variant="page"` with a new `limit={3}` prop. The API already orders by `updated_at` descending (`v1.py`), so the client takes the first three; the API is unchanged. The "All conversations" link to `/conversations` shows whenever there is at least one conversation.
- Empty, loading and error states keep today's components and words: "No conversations yet." and "Could not load conversations.". For a no-history tenant the list stays empty, as today.
- The top-bar item becomes "Home" (`to: "/"`). `CHAT_PATHS` gains `/conversations`, so the item stays current on every chat page.
- Layout: content width 50rem (800 px), sections 32 px apart, the page gutter of the design direction (32 px desktop, 16 px phone). At 390 px the settings row wraps and the submit button keeps its 44 px target. No new tokens.
- The chat rail's "New conversation" still goes to `/new`; `/new` stays as is.
- Tests: on `/`, the order is AI notice, top bar, welcome, question box, recent. A question asked on `/` reaches `/c/:id` with a cited answer (the `start.spec.ts` flow, run from `/`). The spend-cap notice and no-history flow work from `/`. The external-model note shows on `/` when an external model is chosen. With five conversations, exactly three rows show, each with "Expires", and the link leads to all five.

**HP-05 Contract, snapshots and documents.**
- `complianceUi.spec.ts`:
  - add `/conversations` to the gated routes;
  - assert "Expires" on the home page's rows;
  - assert the external-model note on the home page's start panel;
  - assert that no text on `/` names a retention longer than 30 days.

  These tests are written before HP-04's visual changes land, and they are not edited in the same PR as a visual change (UX-03 rule).
- New visual and screen-reader scenarios at 1440 and 390 px: home first visit; home with the welcome hidden; home with one workspace and one model; home for a no-history tenant; home with no workspace; `/conversations`.
- Documents:
  - `design/ux/design-direction.md`: in the app shell, the nav item becomes "Home", and the page list gains the home page and `/conversations`;
  - architecture §7.1: the analyst features gain a "Home page" line;
  - the UX refresh spec's binding list: point item 4 at both the home rows and `/conversations`;
  - this spec: mark each item built.

## Open items for the owner

All four were decided by the owner on Oct 26, 2026.

1. ~~**Which phase this belongs to.**~~ Decided: its own small phase, as the UX refresh was, built HP-01 to HP-05 in order (it is not in the Phase 2A spec).
2. ~~**Wording.**~~ Decided: the wording table as proposed, with "Ask" on the home page's submit button.
3. ~~**How "Hide" is remembered.**~~ Decided: (a), browser storage.
   - (a) **Browser storage** (recommended for now): no API or database change. The card comes back on another browser or device, or after site data is cleared. The value is a UI preference the user set themselves, holds no personal data, and is never sent to the server.
   - (b) **On the server**, per user: a nullable `welcome_hidden_at` on the user row and a `PATCH /me/preferences` route. That is an Alembic migration on a tenant-scoped table, plus an API change, audit and tests. It is out of this spec unless chosen.
4. ~~**Showing the welcome again after Hide.**~~ Decided: as proposed (backlog line). Proposal: nothing in this spec. With (a) it returns when site data is cleared. A "Show the welcome" item in the user menu would be new copy and can follow if users ask for it.
