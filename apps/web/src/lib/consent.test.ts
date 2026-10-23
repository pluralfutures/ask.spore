import { describe, expect, it } from "vitest";

import type { Me } from "../api/types";
import { gateApplies, mustAccept } from "./consent";

// Synthetic people only (CLAUDE.md).
const me = (consent_required: boolean): Me => ({
  email: "user@client.example",
  display_name: "Synthetic User",
  role: "user",
  tenant_display_name: "Synthetic Client",
  consent_required,
  operator: false,
});

describe("consent gate (P1b-10)", () => {
  it("gates conversations, files and the tenant admin pages", () => {
    for (const path of ["/", "/new", "/c/abc", "/w/abc/files", "/admin"]) {
      expect(gateApplies(path)).toBe(true);
      expect(mustAccept(me(true), path)).toBe(true);
      expect(mustAccept(me(false), path)).toBe(false);
    }
  });

  it("does not gate the operator and content consoles", () => {
    for (const path of ["/operator", "/operator/tenants/t1", "/content", "/content/sites"]) {
      expect(gateApplies(path)).toBe(false);
      expect(mustAccept(me(true), path)).toBe(false);
    }
    expect(gateApplies("/operatorx")).toBe(true);
  });

  it("waits for the user before deciding", () => {
    expect(mustAccept(undefined, "/")).toBe(false);
  });
});
