import { describe, expect, it } from "vitest";

import type { EntitlementsOut } from "../api/types";
import { formFrom, toRequest } from "./entitlements";

const off: EntitlementsOut = {
  answer_modes: ["corpus_only"],
  enabled_models: ["deepseek-v4.1-flash"],
  external_models_enabled: false,
  external_spend_cap_cents: null,
  sign_in_links_enabled: true,
  external_acceptance_reference: null,
  external_acceptance_date: null,
  updated_at: "2026-10-19T10:00:00Z",
};

describe("toRequest", () => {
  it("refuses to switch external models on without the acceptance", () => {
    const form = { ...formFrom(off), externalModelsEnabled: true, spendCapEuros: "500" };
    expect(toRequest(form, off)).toEqual({
      error: "External models need the client's acceptance: DPA document and date.",
    });
  });

  it("refuses external models without a spend cap", () => {
    const form = {
      ...formFrom(off),
      externalModelsEnabled: true,
      acceptanceReference: "DPA-SYN-001",
      acceptanceDate: "2026-10-15",
    };
    expect(toRequest(form, off)).toEqual({ error: "External models need a monthly spend cap." });
  });

  it("sends the acceptance and the cap in cents", () => {
    const form = {
      ...formFrom(off),
      externalModelsEnabled: true,
      spendCapEuros: "500",
      acceptanceReference: " DPA-SYN-001 ",
      acceptanceDate: "2026-10-15",
    };
    const result = toRequest(form, off);
    expect(result).toHaveProperty("body");
    if ("body" in result) {
      expect(result.body.external_spend_cap_cents).toBe(50000);
      expect(result.body.external_acceptance).toEqual({
        reference: "DPA-SYN-001",
        accepted_on: "2026-10-15",
      });
    }
  });

  it("needs no new acceptance when external models are already on", () => {
    const on = { ...off, external_models_enabled: true, external_spend_cap_cents: 50000 };
    const result = toRequest({ ...formFrom(on), spendCapEuros: "800" }, on);
    expect("body" in result && result.body.external_acceptance).toBeNull();
  });
});
