# Screen-reader check (UX-24)

Oct 24, 2026 · Owner decision of Oct 24, 2026: the screen-reader pass of UX-24 is done as an automated check plus a short human confirmation (about 30 minutes), instead of a full manual pass. This note records the automated part, what it found and fixed, and the brief for the human part.

## 1. Automated check

`apps/web/e2e/screenReader.spec.ts`, run with the rest of `pnpm test:e2e` against the fake API.

- **Accessibility tree.** The tree a screen reader reads (roles, names, states, reading order) is recorded for the five flows the spec names: sign-in (email, link sent, second-factor setup and code), consent (changed notice, load error), start (choices, refusal), chat with citations (searching, answer with the sources open at 1440 and 390 px, error, notes and labels) and tenant admin (page, remove dialog). The records are in `apps/web/e2e/screenReader.spec.ts-snapshots/`; a change to any of them fails the suite until it is reviewed and accepted, like a screenshot.
- **Focus.** Skip to content, the citation panel at both widths (opening, Escape, Close), the remove dialog (opening, Cancel), and sign-in.
- **Announcements.** "Searching your research package…" is a polite status; a streamed answer is written into a polite live region; the start refusal and the consent load error are alerts; the chat error is in the live region; the spend-cap fallback is a status.
- **Names in context.** The conversation header, the workspace settings groups and "View at source".

It does not run a screen reader: it checks what the page gives one. Speech output (what NVDA or VoiceOver actually says, and when) is the human part below.

## 2. Findings and fixes

| # | Flow | Finding | Fix |
|---|------|---------|-----|
| 1 | Start, chat | "Skip to content" landed on the conversation rail, so a keyboard or screen-reader user still had to pass every conversation (two stops each) to reach the page. | The skip link now lands on the page itself where there is a rail (`WithRail`, `SKIP_TARGET`); the rail stays in the tab order after the top bar. |
| 2 | Chat | Opening a source left focus on the marker: nothing told a screen-reader user that the panel had opened, and on a phone the sheet covers the thread. | Opening a source moves focus to the panel's "Sources" heading, so the panel is announced and reading continues into the sources. |
| 3 | Chat | Closing the panel dropped focus to the top of the page. | Escape or Close returns focus to the marker that opened it. |
| 4 | Chat | The conversation header (workspace, model, reasoning, mode, expiry) was read as one run of words: "Synthetic Markets Synthetic EU Standard General knowledge Expires 18 Nov 2026". | The header is a list, one item per setting. |
| 5 | Tenant admin | Each workspace repeats "Default mode", "Default model", "Save defaults" and "Additional instructions"; in a list of controls nothing said which workspace a control belonged to. | Each workspace card is a group named by the workspace (`Card group`). |
| 6 | Chat | "View at source" links are identical out of context (a screen reader's list of links). | Each link is described by its source's title (`aria-describedby`), with no new words. |

No visual change: the visual suite passed unchanged.

## 3. Not fixed, needing copy (backlog)

- "View at source" opens a new tab without saying so. Saying it ("opens in a new tab") is new copy.
- Every sign-in step has the same `h1`, "SporeBot". Step headings ("Sign in", "Check your email", "Confirm it's you") would help, but they are new copy.

## 4. Human confirmation (about 30 minutes)

Someone outside the build, ideally a daily screen-reader user, on staging, with NVDA and Chrome or Firefox on Windows, or VoiceOver and Safari on a Mac. Optional: VoiceOver on an iPhone for the phone layout.

Check, in this order (the first is the one the automated check cannot cover at all):

1. **A streamed answer.** Ask a question. Is "Searching your research package…" read? Is the answer read sensibly as it arrives, or is it choppy, repeated or cut off? When it finishes, is anything read again?
2. **Citations.** Open a source from a marker in the answer. Is the "Sources" panel announced? Can you read the source (title, publisher, date, page, excerpt) and reach "View at source"? Does Escape bring you back to the marker?
3. **Consent.** Can you read the full notice, tick the box and accept, without help?
4. **Sign-in.** Can you sign in with the email link and, as an admin, the second-factor code? Is it clear at each step where you are?
5. **Tenant admin.** Move through the sections. Can you change a user's role, open a row's actions and cancel a removal? Is it clear which workspace a setting belongs to?

For each problem, note the page, what you did, what you heard, what you expected, and whether it blocks the task, confuses, or is minor. Note the screen reader, browser and versions used.

Results: _to be added after the human confirmation._
