import { describe, expect, it } from "vitest";

import type { UsageOut } from "../api/types";
import { usageDays, usageModes, usageTotals } from "./usage";

const usage = (extra: Partial<UsageOut> = {}): UsageOut => ({
  since: "2026-10-23",
  until: "2026-10-25",
  questions: [],
  active_users: [],
  top_sources: [],
  cost_month: null,
  costs: null,
  ...extra,
});

describe("usage days", () => {
  it("has one zero row per day when nothing happened", () => {
    expect(usageDays(usage())).toEqual([
      { day: "2026-10-23", byMode: {}, questions: 0, users: 0 },
      { day: "2026-10-24", byMode: {}, questions: 0, users: 0 },
      { day: "2026-10-25", byMode: {}, questions: 0, users: 0 },
    ]);
    expect(usageTotals(usage())).toEqual({ questions: 0, byMode: {}, busiestDayUsers: 0 });
  });

  it("puts each count on its day and mode", () => {
    const u = usage({
      questions: [
        { day: "2026-10-24", mode: "corpus_only", questions: 3 },
        { day: "2026-10-24", mode: "general_knowledge", questions: 1 },
        { day: "2026-10-25", mode: "corpus_only", questions: 2 },
      ],
      active_users: [
        { day: "2026-10-24", users: 2 },
        { day: "2026-10-25", users: 1 },
      ],
    });
    const days = usageDays(u);
    expect(days[1]).toEqual({
      day: "2026-10-24",
      byMode: { corpus_only: 3, general_knowledge: 1 },
      questions: 4,
      users: 2,
    });
    expect(days[0]?.questions).toBe(0);
    expect(usageTotals(u)).toEqual({
      questions: 6,
      byMode: { corpus_only: 5, general_knowledge: 1 },
      busiestDayUsers: 2,
    });
    expect(usageModes(u)).toEqual(["corpus_only", "general_knowledge"]);
  });

  it("crosses a month end", () => {
    const days = usageDays(usage({ since: "2026-10-30", until: "2026-11-02" }));
    expect(days.map((d) => d.day)).toEqual([
      "2026-10-30",
      "2026-10-31",
      "2026-11-01",
      "2026-11-02",
    ]);
  });
});
