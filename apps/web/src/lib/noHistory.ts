import type { ConversationCreated, ConversationCreateIn } from "../api/types";

// P1b-14: a tenant with a retention of 0 days keeps no chat history. Its conversations
// are created already expired (never listed or readable), take one question, and are
// deleted when the answer ends; a follow-up question starts a new conversation with the
// same workspace, mode, model and reasoning, without the earlier turns.

export const NO_HISTORY_NOTE =
  "Your organisation keeps no chat history: each answer is deleted when it ends, and a " +
  "follow-up question starts afresh, without the earlier questions.";

export function keepsNoHistory(created: ConversationCreated | null | undefined): boolean {
  return created?.no_history === true;
}

// The body that starts the next one-question conversation with the same fixed choice.
export function sameChoice(created: ConversationCreated): ConversationCreateIn {
  return {
    workspace_id: created.workspace_id,
    mode: created.mode === "general_knowledge" ? "general_knowledge" : "corpus_only",
    model: created.model,
    reasoning: created.reasoning,
  };
}
