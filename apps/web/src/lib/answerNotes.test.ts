import { describe, expect, it } from "vitest";

import { CUT_OFF_NOTE, PARTIAL_NOTE, answerNote, hasBody } from "./answerNotes";

describe("answer notes (P1c-09)", () => {
  it("notes a cut-off answer and a partial one, and nothing for a complete one", () => {
    expect(answerNote({ truncated: true, partial: false })).toBe(CUT_OFF_NOTE);
    expect(answerNote({ truncated: false, partial: true })).toBe(PARTIAL_NOTE);
    expect(answerNote({ truncated: false, partial: false })).toBeNull();
    expect(answerNote({})).toBeNull();
  });

  it("prefers the partial note when an answer is both", () => {
    expect(answerNote({ truncated: true, partial: true })).toBe(PARTIAL_NOTE);
  });

  it("renders no body for a partial answer stopped before any text", () => {
    expect(hasBody("", { partial: true })).toBe(false);
    expect(hasBody("Capacity grew [1]", { partial: true })).toBe(true);
    expect(hasBody("", { partial: false })).toBe(true);
  });
});
