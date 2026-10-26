import type { Page } from "@playwright/test";

import { ScenarioApi } from "./scenarioApi";
import { conversationDetails, type Scenario } from "./scenarios";

// Installs the scenario's fake API, opens its URL and brings it into its state. Scenarios
// that leave a route unanswered (loading states) never reach network idle, so the wait for
// it is bounded; the visual suite's screenshot comparison waits for a stable page anyway.
export async function openScenario(page: Page, scenario: Scenario): Promise<ScenarioApi> {
  const api = new ScenarioApi({ conversationDetail: conversationDetails(), ...scenario.options });
  await api.install(page);
  page.on("dialog", (dialog) => void dialog.accept());
  await page.goto(scenario.url);
  await settle(page);
  if (scenario.act) {
    await scenario.act(page);
    await settle(page);
  }
  return api;
}

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle", { timeout: 2_000 }).catch(() => undefined);
  // A string, so the Node-typed e2e config needs no DOM types.
  await page.evaluate("document.fonts.ready.then(() => undefined)");
}
