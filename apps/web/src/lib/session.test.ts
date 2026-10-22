import { describe, expect, it } from "vitest";

import { MIN_DELAY_MS, RENEW_BEFORE_MS, renewalDelay } from "./session";

describe("renewalDelay", () => {
  const now = Date.parse("2026-10-21T10:00:00Z");

  it("renews five minutes before the access token expires", () => {
    expect(renewalDelay("2026-10-21T18:00:00Z", now)).toBe(8 * 3600 * 1000 - RENEW_BEFORE_MS);
  });

  it("waits at least half a minute, even when the expiry is close or past", () => {
    expect(renewalDelay("2026-10-21T10:01:00Z", now)).toBe(MIN_DELAY_MS);
    expect(renewalDelay("2026-10-21T09:00:00Z", now)).toBe(MIN_DELAY_MS);
  });

  it("does nothing without a known expiry", () => {
    expect(renewalDelay(null, now)).toBeNull();
    expect(renewalDelay("not a date", now)).toBeNull();
  });
});
