import { describe, expect, it } from "vitest";

import { statusTone } from "./status";

describe("status tones (UX-08)", () => {
  it("colours each status by what it means", () => {
    expect(statusTone("user", "active")).toBe("success");
    expect(statusTone("user", "invited")).toBe("accent");
    expect(statusTone("source", "failed")).toBe("danger");
    expect(statusTone("job", "succeeded")).toBe("success");
    expect(statusTone("takedown", "open")).toBe("warning");
  });

  it("an unknown status is neutral", () => {
    expect(statusTone("site", "something-new")).toBe("neutral");
  });
});
