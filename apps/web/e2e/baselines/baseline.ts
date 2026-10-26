import { readFileSync } from "node:fs";

// UX-02: today's known accessibility and layout failures (ux-baseline.json). Entries are only
// ever removed; see the file's note.
export interface Baseline {
  axe: Record<string, string[]>;
  overflowAt390: Record<string, number>;
  focusRingMinWidthPx: number;
}

export const BASELINE = JSON.parse(
  readFileSync(new URL("./ux-baseline.json", import.meta.url), "utf8"),
) as Baseline;
