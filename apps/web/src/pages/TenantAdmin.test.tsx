import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { adminApi } from "../api/client";
import type { AdminUser, Me } from "../api/types";
import {
  auditLogQuery,
  consentStatus,
  defaultAuditPeriod,
  lastLogin,
  parseRetention,
  retentionSummary,
  userActions,
  usersHeading,
} from "../lib/admin";
import { AdminGate, UsageView, VersionHistory } from "./TenantAdmin";

// Synthetic people only (CLAUDE.md).
const me = (role: Me["role"]): Me => ({
  email: "admin@client.example",
  display_name: "Synthetic Admin",
  role,
  tenant_display_name: "Synthetic Client",
  consent_required: false,
  operator: false,
});
const user = (extra: Partial<AdminUser> = {}): AdminUser => ({
  id: "u1",
  email: "member@client.example",
  display_name: "Synthetic Member",
  role: "user",
  status: "active",
  last_login_at: "2026-10-18T09:00:00Z",
  last_login_method: "sign_in_link",
  created_at: "2026-10-01T09:00:00Z",
  consent_version: "v1",
  consent_current: true,
  ...extra,
});

describe("AdminGate", () => {
  it("does not open the admin pages for the user role", () => {
    const html = renderToString(
      <AdminGate me={me("user")}>
        <p>Users</p>
      </AdminGate>,
    );
    expect(html).toContain("Tenant admins only.");
    expect(html).not.toContain("Users");
    // UX-23: the sentence is the page's h1, in an empty state.
    expect(html).toMatch(/<h1[^>]*>Tenant admins only\.<\/h1>/);
  });

  it("does not open them without a signed-in user", () => {
    const html = renderToString(
      <AdminGate me={null}>
        <p>Users</p>
      </AdminGate>,
    );
    expect(html).toContain("Tenant admins only.");
  });

  it("opens them for a tenant admin", () => {
    const html = renderToString(
      <AdminGate me={me("tenant_admin")}>
        <p>Users</p>
      </AdminGate>,
    );
    expect(html).toContain("Users");
  });
});

describe("retention", () => {
  it("cannot be set above 30 days", () => {
    expect(parseRetention("31")).toEqual({ error: "Retention cannot exceed 30 days." });
    expect(parseRetention("365")).toEqual({ error: "Retention cannot exceed 30 days." });
  });

  it("accepts 0 to 30 whole days", () => {
    expect(parseRetention("30")).toEqual({ days: 30 });
    expect(parseRetention(" 7 ")).toEqual({ days: 7 });
    expect(parseRetention("1")).toEqual({ days: 1 });
    expect(parseRetention("0")).toEqual({ days: 0 });
    expect(parseRetention("-1")).toEqual({ error: "Retention cannot be negative." });
    expect("error" in parseRetention("2.5")).toBe(true);
    expect("error" in parseRetention("")).toBe(true);
  });
});

describe("retention summary", () => {
  it("says what 0 means", () => {
    expect(retentionSummary(0)).toContain("No history");
    expect(retentionSummary(1)).toBe("Conversations are deleted 1 day after they start.");
    expect(retentionSummary(30)).toBe("Conversations are deleted 30 days after they start.");
  });
});

describe("users", () => {
  it("shows last login and method", () => {
    expect(lastLogin(user())).toBe("18 Oct 2026 · sign-in link");
    expect(lastLogin(user({ last_login_at: null, last_login_method: null }))).toBe(
      "Never signed in",
    );
  });

  it("offers no change of one's own role or status", () => {
    const self = user({ email: "admin@client.example", role: "tenant_admin" });
    expect(userActions(self, "admin@client.example")).toEqual({
      canChangeRole: false,
      canDeactivate: false,
      canReactivate: false,
      canResend: false,
      canRemove: false,
    });
    expect(userActions(user(), "admin@client.example")).toEqual({
      canChangeRole: true,
      canDeactivate: true,
      canReactivate: false,
      canResend: false,
      canRemove: true,
    });
    expect(userActions(user({ status: "deactivated" }), "admin@client.example").canReactivate).toBe(
      true,
    );
  });

  it("offers a resend only while the user is invited (P1c-07)", () => {
    expect(userActions(user({ status: "invited" }), "admin@client.example").canResend).toBe(true);
    expect(userActions(user({ status: "active" }), "admin@client.example").canResend).toBe(false);
  });
});

describe("VersionHistory", () => {
  it("lists every saved version newest first, with no revert", () => {
    const html = renderToString(
      <VersionHistory
        versions={[
          { version: 2, text: "Synthetic second.", created_at: "2026-10-19T09:00:00Z" },
          { version: 1, text: "Synthetic first.", created_at: "2026-10-18T09:00:00Z" },
        ]}
      />,
    );
    expect(html.indexOf('data-testid="version-2"')).toBeLessThan(
      html.indexOf('data-testid="version-1"'),
    );
    expect(html).toContain("Synthetic second.");
    expect(html).not.toMatch(/<button/);
    expect(html.toLowerCase()).not.toContain("revert");
  });
});

describe("usage section (P2A-05)", () => {
  const base = {
    since: "2026-09-26",
    until: "2026-10-25",
    questions: [{ day: "2026-10-25", mode: "corpus_only", questions: 4 }],
    active_users: [{ day: "2026-10-25", users: 2 }],
    top_sources: [{ title: "Synthetic Wind Report", publisher: "Synthetic Institute", answers: 3 }],
    cost_month: null,
    costs: null,
  };

  it("shows counts and cited sources, and no cost without external models", () => {
    const html = renderToString(<UsageView usage={base} />);
    expect(html).toContain("Synthetic Wind Report");
    expect(html).toContain("Sources only");
    expect(html).toContain("Most active users in a day");
    expect(html).not.toContain("Cost this month");
  });

  it("shows the month's cost per model with external models", () => {
    const html = renderToString(
      <UsageView
        usage={{
          ...base,
          cost_month: "2026-10",
          costs: [
            {
              model: "openai/gpt-6.1-sol",
              display_name: "Synthetic External",
              external: true,
              tokens_in: 100,
              tokens_out: 50,
              cost_cents: "1250.000000",
            },
          ],
        }}
      />,
    );
    expect(html).toContain("Cost this month (2026-10)");
    expect(html).toContain("Synthetic External (external)");
    expect(html).toContain("€12.50");
  });

  it("says when there were no questions", () => {
    const html = renderToString(
      <UsageView usage={{ ...base, questions: [], active_users: [], top_sources: [] }} />,
    );
    expect(html).toContain("No questions in this period.");
    expect(html).toContain("No cited sources in this period.");
  });
});

describe("consent status per user (P2A-06)", () => {
  it("marks a user who accepted an older notice", () => {
    expect(consentStatus(user({ consent_version: "v1", consent_current: false }))).toBe(
      "v1 (older notice)",
    );
    expect(consentStatus(user({ consent_version: "v2", consent_current: true }))).toBe(
      "v2 (current)",
    );
    expect(consentStatus(user({ consent_version: null, consent_current: false }))).toBe(
      "Not accepted",
    );
  });

  it("names the active notice version in the heading", () => {
    expect(usersHeading("v2")).toBe("Users · notice v2");
    expect(usersHeading(undefined)).toBe("Users");
  });
});

describe("audit export (P2A-07)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("builds the query from the chosen dates and the next part's cursor", () => {
    expect(auditLogQuery("2026-09-01", "2026-09-30")).toBe("?since=2026-09-01&until=2026-09-30");
    expect(auditLogQuery("2026-09-01", "2026-09-30", "2026-09-02T00:00:00+00:00|e1")).toBe(
      "?since=2026-09-01&until=2026-09-30&after=2026-09-02T00%3A00%3A00%2B00%3A00%7Ce1",
    );
    expect(auditLogQuery("", "")).toBe("");
  });

  it("defaults to the last 90 days", () => {
    expect(defaultAuditPeriod(new Date("2026-10-25T10:00:00Z"))).toEqual({
      since: "2026-07-27",
      until: "2026-10-25",
    });
  });

  it("downloads from the route with the chosen dates and reads the paging headers", async () => {
    const fetchSpy = vi.fn(
      async () =>
        new Response("created_at,event,actor_user_id,metadata\n", {
          status: 200,
          headers: {
            "content-type": "text/csv",
            "content-disposition": 'attachment; filename="audit-log-2026-09-01-2026-09-30.csv"',
            "x-audit-export-complete": "false",
            "x-audit-export-next": "2026-09-02T00:00:00+00:00|e1",
          },
        }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const file = await adminApi.auditLog("2026-09-01", "2026-09-30");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/admin/audit-log?since=2026-09-01&until=2026-09-30");
    expect(init.method).toBe("GET");
    expect(file).toMatchObject({
      name: "audit-log-2026-09-01-2026-09-30.csv",
      complete: false,
      next: "2026-09-02T00:00:00+00:00|e1",
    });
  });
});
