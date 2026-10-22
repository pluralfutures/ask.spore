import { describe, expect, it } from "vitest";

import { failoverNote } from "./failover";

describe("failoverNote", () => {
  it("says when a backup answered, and where it is served", () => {
    expect(failoverNote("eu")).toContain("hosted in the EU");
    expect(failoverNote("external")).toContain("served outside the EU");
    expect(failoverNote(null)).toBeNull();
    expect(failoverNote(undefined)).toBeNull();
  });
});
