import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AdminUser, Me } from "../api/types";
import { lastLogin, parseRetention, userActions } from "../lib/admin";
import { AdminGate, VersionHistory } from "./TenantAdmin";

// Synthetic people only (CLAUDE.md).
const me = (role: Me["role"]): Me => ({
  email: "admin@client.example",
  display_name: "Synthetic Admin",
  role,
  tenant_display_name: "Synthetic Client",
  consent_required: false,
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

  it("accepts 1 to 30 whole days", () => {
    expect(parseRetention("30")).toEqual({ days: 30 });
    expect(parseRetention(" 7 ")).toEqual({ days: 7 });
    expect(parseRetention("1")).toEqual({ days: 1 });
    expect("error" in parseRetention("0")).toBe(true);
    expect("error" in parseRetention("2.5")).toBe(true);
    expect("error" in parseRetention("")).toBe(true);
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
    });
    expect(userActions(user(), "admin@client.example")).toEqual({
      canChangeRole: true,
      canDeactivate: true,
      canReactivate: false,
    });
    expect(userActions(user({ status: "deactivated" }), "admin@client.example").canReactivate).toBe(
      true,
    );
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
