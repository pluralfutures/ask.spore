import { afterEach, describe, expect, it, vi } from "vitest";

import { contentApi } from "./client";

// P2A-04: the content console's pause, resume and multi-tag list calls.
describe("content API (P2A-04)", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stub(body: unknown) {
    const fetchSpy = vi.fn().mockImplementation(() => Promise.resolve(Response.json(body)));
    vi.stubGlobal("fetch", fetchSpy);
    return () => fetchSpy.mock.calls.map(([url, init]) => [url, init as RequestInit] as const);
  }

  it("repeats the tag parameter for a workspace's tags", async () => {
    const calls = stub([]);
    await contentApi.sources({ tags: ["sample-reports", "sample-web"], status: "paused" });
    expect(calls()[0]?.[0]).toBe(
      "/api/v1/content/sources?tag=sample-reports&tag=sample-web&status=paused",
    );
  });

  it("pauses with the reason only and resumes with no body", async () => {
    const calls = stub({ status: "paused", documents: 2, cache_entries_purged: 0 });
    const id = "33333333-3333-4333-8333-333333333333";
    await contentApi.pause(id, "Synthetic rights check");
    await contentApi.resume(id);
    const [pauseCall, resumeCall] = calls();
    if (!pauseCall || !resumeCall) throw new Error("expected two calls");
    const [pauseUrl, pauseInit] = pauseCall;
    const [resumeUrl, resumeInit] = resumeCall;
    expect([pauseUrl, pauseInit.method]).toEqual([`/api/v1/content/sources/${id}/pause`, "POST"]);
    expect(JSON.parse(pauseInit.body as string)).toEqual({ reason: "Synthetic rights check" });
    expect([resumeUrl, resumeInit.method]).toEqual([
      `/api/v1/content/sources/${id}/resume`,
      "POST",
    ]);
    expect(resumeInit.body ?? null).toBeNull();
  });
});
