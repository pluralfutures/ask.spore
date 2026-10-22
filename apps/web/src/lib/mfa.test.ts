import { describe, expect, it } from "vitest";

import { setupKey, validCode } from "./mfa";

describe("setupKey", () => {
  it("shows the secret of an otpauth URI in groups of four", () => {
    expect(setupKey("otpauth://totp/SporeBot:x?secret=jbswy3dpehpk3pxp&issuer=SporeBot")).toBe(
      "JBSW Y3DP EHPK 3PXP",
    );
  });

  it("shows nothing for anything else", () => {
    expect(setupKey(null)).toBeNull();
    expect(setupKey("https://example.org/?secret=ABCD")).toBeNull();
    expect(setupKey("otpauth://totp/x?secret=not-base32!")).toBeNull();
  });
});

describe("validCode", () => {
  it("takes six to eight digits", () => {
    expect(validCode("123456")).toBe(true);
    expect(validCode(" 12345678 ")).toBe(true);
    expect(validCode("12345")).toBe(false);
    expect(validCode("12a456")).toBe(false);
  });
});
