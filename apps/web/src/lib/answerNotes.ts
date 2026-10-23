// P1c-09: notes under an answer that did not end normally. Both flags are stored on the
// message, so the notes come back with the conversation after a reload.

export const CUT_OFF_NOTE = "This answer was cut off at the length limit.";
export const PARTIAL_NOTE = "This answer was stopped before it finished.";

export interface AnswerFlags {
  truncated?: boolean | null;
  partial?: boolean | null;
}

/** The note shown under an answer, or null for a complete one. */
export function answerNote(flags: AnswerFlags): string | null {
  if (flags.partial) return PARTIAL_NOTE;
  if (flags.truncated) return CUT_OFF_NOTE;
  return null;
}

/** A partial answer stopped before any text was shown has no body to render. */
export function hasBody(text: string, flags: AnswerFlags): boolean {
  return !flags.partial || text.trim() !== "";
}
