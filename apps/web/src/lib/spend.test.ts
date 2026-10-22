import { describe, expect, it } from "vitest";

import { capShare, count, euros } from "./spend";

describe("spend figures", () => {
  it("shows ledger cents as euros", () => {
    expect(euros("2547.000000")).toBe("€25.47");
    expect(euros("0.612000")).toBe("€0.01");
    expect(euros(3000)).toBe("€30.00");
  });

  it("shows the share of the cap, none without a cap", () => {
    expect(capShare("2400", 3000)).toBe(80);
    expect(capShare("2399.99", 3000)).toBe(79);
    expect(capShare("10", null)).toBeNull();
    expect(capShare("0", 0)).toBe(100);
  });

  it("groups token counts", () => {
    expect(count(1234567)).toBe("1,234,567");
  });
});
