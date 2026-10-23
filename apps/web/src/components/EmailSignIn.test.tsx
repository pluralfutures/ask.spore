import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { discoverMethods } from "../api/client";
import { EmailSignIn } from "./EmailSignIn";
import { failureText, ssoRefusalText } from "./emailSignInText";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EmailSignIn", () => {
  it("asks for the address first and calls nothing on render", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const html = renderToString(<EmailSignIn />);
    expect(html).toContain('type="email"');
    expect(html).toContain("Continue");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("failureText", () => {
  it("says when the network is rate limited", () => {
    expect(failureText(true)).toContain("Too many sign-in attempts");
    expect(failureText(false)).toBe("Something went wrong. Try again.");
  });
});

describe("discoverMethods", () => {
  it("POSTs the address to tenant discovery and returns the methods", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(Response.json({ methods: ["sso", "sign_in_link"], sso_kind: "entra" }));
    vi.stubGlobal("fetch", fetchSpy);
    expect(await discoverMethods("someone@client.example")).toEqual({
      methods: ["sso", "sign_in_link"],
      sso_kind: "entra",
    });
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/discover");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ email: "someone@client.example" });
  });
});

describe("ssoRefusalText (P1c-02)", () => {
  it("says why a refused SSO sign-in was refused, for each reason the API sends", () => {
    expect(ssoRefusalText("domain")).toContain("not at a domain this workspace accepts");
    expect(ssoRefusalText("unverified")).toContain("has not verified this email address");
    expect(ssoRefusalText("no_access")).toContain("Ask your administrator to invite you");
    expect(ssoRefusalText("start_again")).toContain("Start again in this browser");
  });

  it("falls back to the generic text for no reason or one it does not know", () => {
    for (const reason of [null, "", "failed", "domain_not_verified", "toString"]) {
      expect(ssoRefusalText(reason)).toContain("Single sign-on did not complete");
    }
  });

  it("shows the refusal on the sign-in page", () => {
    const html = renderToString(<EmailSignIn ssoFailed ssoReason="domain" />);
    expect(html).toContain("not at a domain this workspace accepts");
    expect(html).toContain('role="alert"');
    expect(renderToString(<EmailSignIn />)).not.toContain('role="alert"');
  });
});
