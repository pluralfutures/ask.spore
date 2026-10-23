import { describe, expect, it } from "vitest";

import { encodeQr, penalty, qrPath } from "./qr";

// Reference matrices from an independent encoder (python-qrcode 8, error correction M,
// byte mode, the mask named), dark = "1". The encoder was also checked against it for
// versions 1 to 29 and every mask while it was written (P1c-08).
// prettier-ignore
const HELLO_MASK_0 = [
  "111111100110001111111",
  "100000101100001000001",
  "101110100101101011101",
  "101110100011001011101",
  "101110101100101011101",
  "100000100000101000001",
  "111111101010101111111",
  "000000000011100000000",
  "101010100101000010010",
  "001011000010001000011",
  "010100101110100011111",
  "110010000000001000010",
  "011010110010101010000",
  "000000001111010100111",
  "111111100011011100111",
  "100000100011110110000",
  "101110101011011100011",
  "101110100100001100110",
  "101110101110100010101",
  "100000100100001010010",
  "111111101110101100011",
];
// prettier-ignore
const OTPAUTH_MASK_3 = [
  "111111101111101010111011001111111",
  "100000101010001011001101001000001",
  "101110100001011110100000101011101",
  "101110101010100100100000101011101",
  "101110100011000010100011101011101",
  "100000100110000111100010001000001",
  "111111101010101010101010101111111",
  "000000001111101111110001000000000",
  "101101110100001111100110101001011",
  "010101011101010011001101011101100",
  "000111101000110010100101101001011",
  "101001000011100001011001101001000",
  "110111101011001110001111010011011",
  "000100001100001001001111101001110",
  "110000111010010000111100011110100",
  "001101011010111100100110101111111",
  "001000110111011000001010001011010",
  "101010000110110100101001111110001",
  "110101100000100110100100110100100",
  "011001011010011101111001101100001",
  "100100110101001010010000000110100",
  "110000001000110111001110010000101",
  "000101101111110100011101110111111",
  "011010000001001100001000101111000",
  "100111111101110011011010111111100",
  "000000001010111110110110100011010",
  "111111101110011001111011101011000",
  "100000101010110011111101100011110",
  "101110100111011111111011111110111",
  "101110101111110011010001110100001",
  "101110101111111110100101001001000",
  "100000100011100001001001001100001",
  "111111101110111001010101010111000",
];
const OTPAUTH = "otpauth://totp/SporeBot:x?secret=JBSWY3DPEHPK3PXP";

const rows = (m: boolean[][]) => m.map((r) => r.map((c) => (c ? "1" : "0")).join(""));

describe("QR encoder (P1c-08)", () => {
  it("matches the reference encoder", () => {
    expect(rows(encodeQr("hello", "M", 0))).toEqual(HELLO_MASK_0);
    expect(rows(encodeQr(OTPAUTH, "M", 3))).toEqual(OTPAUTH_MASK_3);
  });

  it("picks the smallest version and the mask of lowest penalty", () => {
    const auto = encodeQr(OTPAUTH);
    expect(auto.length).toBe(33); // version 4
    const scores = [0, 1, 2, 3, 4, 5, 6, 7].map((m) => penalty(encodeQr(OTPAUTH, "M", m)));
    expect(penalty(auto)).toBe(Math.min(...scores));
    // A full Authentik URI (issuer, label, 32-character secret) fits version 8.
    const full =
      "otpauth://totp/SporeBot:admin%40client.example?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP" +
      "&issuer=SporeBot&algorithm=SHA1&digits=6&period=30";
    expect(encodeQr(full).length).toBe(49);
  });

  it("draws finder patterns in three corners", () => {
    const m = rows(encodeQr(OTPAUTH));
    const n = m.length;
    const corners: [number, number][] = [
      [0, 0],
      [n - 7, 0],
      [0, n - 7],
    ];
    for (const [x, y] of corners) {
      expect(m[y]?.slice(x, x + 7)).toBe("1111111");
      expect(m[y + 1]?.slice(x, x + 7)).toBe("1000001");
      expect(m[y + 3]?.slice(x, x + 7)).toBe("1011101");
    }
  });

  it("refuses text longer than version 40 holds", () => {
    expect(() => encodeQr("x".repeat(3000))).toThrow("too long");
  });

  it("draws the dark modules as one path inside a quiet zone", () => {
    const { d, size } = qrPath([
      [true, false],
      [false, true],
    ]);
    expect(size).toBe(10);
    expect(d).toBe("M4,4h1v1h-1zM5,5h1v1h-1z");
  });
});
