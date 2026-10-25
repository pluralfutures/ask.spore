import { describe, expect, it } from "vitest";

import type { SupportGrant } from "../api/types";
import { canRevoke, durationLabel, grantRefusal, grantScope, viewsLabel } from "./support";

const grant = (extra: Partial<SupportGrant> = {}): SupportGrant => ({
  id: "g1",
  scope: "settings",
  conversation_id: null,
  conversation_title: null,
  duration_minutes: 60,
  note: "Synthetic note.",
  created_at: "2026-10-25T10:00:00Z",
  expires_at: "2026-10-25T11:00:00Z",
  revoked_at: null,
  state: "open",
  views: 0,
  last_viewed_at: null,
  ...extra,
});

describe("support grants (P2A-08)", () => {
  it("labels durations from 15 minutes to 4 hours", () => {
    expect([15, 30, 60, 120, 240].map(durationLabel)).toEqual([
      "15 minutes",
      "30 minutes",
      "1 hour",
      "2 hours",
      "4 hours",
    ]);
  });

  it("offers revoke only while the grant is open", () => {
    expect(canRevoke(grant())).toBe(true);
    expect(canRevoke(grant({ state: "used", views: 2 }))).toBe(true);
    expect(canRevoke(grant({ state: "expired" }))).toBe(false);
    expect(canRevoke(grant({ state: "revoked" }))).toBe(false);
  });

  it("names what the grant covers and how often it was read", () => {
    expect(grantScope(grant())).toBe("Settings");
    expect(
      grantScope(
        grant({ scope: "conversation", conversation_id: "c1", conversation_title: "Synthetic" }),
      ),
    ).toBe("Conversation: Synthetic");
    expect(viewsLabel(grant())).toBe("Not viewed");
    expect(viewsLabel(grant({ views: 1 }))).toBe("Viewed once");
    expect(viewsLabel(grant({ views: 3 }))).toBe("Viewed 3 times");
  });

  it("explains a refusal", () => {
    expect(grantRefusal("conversation_not_found")).toContain("not one of yours");
    expect(grantRefusal(null)).toBe("The access could not be granted.");
  });
});
