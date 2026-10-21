import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { answerMfa, completeSignIn } from "../api/client";
import { tokenFromFragment } from "../lib/fragment";
import { FinishSignIn, SecondFactor } from "./FinishSignIn";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("tokenFromFragment", () => {
  it("reads the token from the fragment only", () => {
    expect(tokenFromFragment("#token=abc-123")).toBe("abc-123");
    expect(tokenFromFragment("token=abc")).toBe("abc");
    expect(tokenFromFragment("")).toBeNull();
    expect(tokenFromFragment("#other=1")).toBeNull();
    expect(tokenFromFragment(`#token=${"x".repeat(600)}`)).toBeNull();
  });
});

describe("FinishSignIn", () => {
  it("renders one button and submits nothing when the page opens", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const html = renderToString(<FinishSignIn initialToken="abc" onSignedIn={() => {}} />);
    expect(html).toContain("Click to finish logging in");
    expect(html.match(/<button/g)).toHaveLength(1);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("explains an unusable link without a button", () => {
    const html = renderToString(<FinishSignIn initialToken={null} onSignedIn={() => {}} />);
    expect(html).toContain("cannot be used");
    expect(html).not.toContain("<button");
  });
});

describe("completeSignIn", () => {
  it("POSTs the token once, as JSON, with same-origin cookies", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    expect(await completeSignIn("abc", fetchImpl)).toBe("ok");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/link/complete");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(JSON.parse(init.body as string)).toEqual({ token: "abc" });
  });

  it("reports a refused link", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    expect(await completeSignIn("used", fetchImpl)).toBe("failed");
  });

  it("tells a link opened in another browser apart (P1b-08)", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(Response.json({ detail: "no_binding" }, { status: 401 }));
    expect(await completeSignIn("abc", fetchImpl)).toBe("no_binding");
  });
});

describe("second factor (P1b-08)", () => {
  const challenge = {
    status: "mfa_required" as const,
    stage: "setup" as const,
    setup_uri: "otpauth://totp/ask.spore:x?secret=JBSWY3DPEHPK3PXP",
    failed: false,
  };

  it("passes the challenge on from the link POST", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(Response.json(challenge, { status: 200 }));
    expect(await completeSignIn("abc", fetchImpl)).toEqual(challenge);
  });

  it("shows the enrolment key and asks for the code", () => {
    const html = renderToString(<SecondFactor challenge={challenge} onResult={() => {}} />);
    expect(html).toContain("JBSW Y3DP EHPK 3PXP");
    expect(html).toContain("one-time-code");
  });

  it("POSTs the code to the MFA route", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    expect(await answerMfa("123456", fetchImpl)).toBe("ok");
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/mfa");
    expect(JSON.parse(init.body as string)).toEqual({ code: "123456" });
  });
});
