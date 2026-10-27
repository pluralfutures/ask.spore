import { describe, expect, it } from "vitest";

import type { WorkspaceSummary } from "../api/types";
import { countLine, publishersLine, updatedLine, yearsLine } from "./workspaceSummary";

// Synthetic figures only (CLAUDE.md).
const base: WorkspaceSummary = {
  document_count: 128,
  publisher_count: 14,
  top_publishers: ["Publisher A", "Publisher B", "Publisher C"],
  first_year: 2019,
  last_year: 2026,
  last_updated: "2026-10-24",
};

describe("workspace summary wording (P2B-05)", () => {
  it("counts documents and publishers, singular and plural", () => {
    expect(countLine(base)).toBe("128 documents from 14 publishers");
    expect(countLine({ ...base, document_count: 1, publisher_count: 1 })).toBe(
      "1 document from 1 publisher",
    );
  });

  it("names the three largest publishers and how many more there are", () => {
    expect(publishersLine(base)).toBe(
      "Including Publisher A, Publisher B, Publisher C and 11 more",
    );
  });

  it("names every publisher when there are three or fewer, with no 'more'", () => {
    const three = { ...base, publisher_count: 3 };
    expect(publishersLine(three)).toBe("From Publisher A, Publisher B and Publisher C");
    const two = { ...base, publisher_count: 2, top_publishers: ["Publisher A", "Publisher B"] };
    expect(publishersLine(two)).toBe("From Publisher A and Publisher B");
    const one = { ...base, publisher_count: 1, top_publishers: ["Publisher A"] };
    expect(publishersLine(one)).toBe("From Publisher A");
  });

  it("gives the years as a range, or one year, and leaves them out when unknown", () => {
    expect(yearsLine(base)).toBe("Published 2019 to 2026");
    expect(yearsLine({ ...base, first_year: 2026 })).toBe("Published in 2026");
    expect(yearsLine({ ...base, first_year: null, last_year: null })).toBeNull();
  });

  it("gives the last update as a date", () => {
    expect(updatedLine(base)).toBe("Last updated 24 Oct 2026");
    expect(updatedLine({ ...base, last_updated: null })).toBeNull();
  });
});
