import { describe, expect, it } from "vitest";

import type { ConversationCreated } from "../api/types";
import { keepsNoHistory, sameChoice } from "./noHistory";

function created(overrides: Partial<ConversationCreated> = {}): ConversationCreated {
  return {
    id: "c-1",
    title: null,
    created_at: "2026-10-22T10:00:00Z",
    expires_at: "2026-10-22T10:00:00Z",
    workspace_id: "w-1",
    mode: "corpus_only",
    model: "deepseek-v4.1-flash",
    reasoning: false,
    notice: null,
    notice_text: null,
    no_history: true,
    ...overrides,
  };
}

describe("no history (retention 0)", () => {
  it("is read from the created conversation", () => {
    expect(keepsNoHistory(created())).toBe(true);
    expect(keepsNoHistory(created({ no_history: false }))).toBe(false);
    expect(keepsNoHistory(null)).toBe(false);
  });

  it("starts the next conversation with the same fixed choice", () => {
    expect(sameChoice(created({ mode: "general_knowledge", reasoning: true }))).toEqual({
      workspace_id: "w-1",
      mode: "general_knowledge",
      model: "deepseek-v4.1-flash",
      reasoning: true,
    });
  });
});
