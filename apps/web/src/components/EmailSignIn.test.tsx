import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { discoverMethods } from "../api/client";
import { EmailSignIn } from "./EmailSignIn";

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
