import { expect, test, type Page, type Route } from "@playwright/test";

// P1c-08: operator console feedback, against a fake API. Synthetic tenants only.
const TENANT_ID = "00000000-0000-4000-8000-00000000000a";
const WORKSPACE_ID = "aaaaaaaa-0000-4000-8000-000000000001";
const tenant = {
  id: TENANT_ID,
  slug: "alpha",
  display_name: "Synthetic Alpha",
  verified_domains: ["alpha.example"],
  status: "active",
  created_at: "2026-10-01T09:00:00Z",
  admins: 1,
  entitlements: {
    answer_modes: ["corpus_only"],
    enabled_models: ["deepseek-v4.1-flash"],
    external_models_enabled: false,
    external_spend_cap_cents: null,
    external_acceptance_reference: null,
    external_acceptance_date: null,
    updated_at: "2026-10-19T10:00:00Z",
  },
  login_policy: {
    sign_in_links_enabled: true,
    sso_source_kind: "none",
    sso_source_slug: null,
    sso_source_config: {},
    jit_provisioning_enabled: false,
    admin_mfa_required: true,
    sso_endpoints: null,
    updated_at: "2026-10-19T10:00:00Z",
  },
};

async function fakeConsole(page: Page, calls: { method: string; path: string }[]) {
  await page.addInitScript(() => {
    sessionStorage.setItem(
      "askspore.phase0.credentials",
      JSON.stringify({ token: "synthetic-token", email: "operator@example.org" }),
    );
  });
  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    calls.push({ method, path });
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body });
    if (path === "/auth/mode") return json({ mode: "phase0" });
    if (path === "/me") {
      return json({
        email: "operator@example.org",
        display_name: "Synthetic Operator",
        role: "user",
        tenant_display_name: "Synthetic Platform",
        consent_required: false,
        operator: true,
      });
    }
    if (path === "/conversations" || path === "/workspaces") return json([]);
    if (path === "/operator/tenants") return json([tenant]);
    if (path === "/operator/terminated-tenants") {
      return json([
        {
          id: "00000000-0000-4000-8000-00000000000c",
          slug: "gone",
          display_name: "Synthetic Gone",
          status: "suspended",
          purged_at: "2026-10-23T07:56:07Z",
          certificate: "COD-20261023-0000beef",
        },
      ]);
    }
    if (path === "/operator/notices" || path === "/operator/sources") return json([]);
    if (path === "/operator/options") {
      return json({ answer_modes: ["corpus_only"], models: ["deepseek-v4.1-flash"], tags: [] });
    }
    if (path === `/operator/tenants/${TENANT_ID}`) return json(tenant);
    if (path === `/operator/tenants/${TENANT_ID}/login-policy` && method === "PUT") {
      return json(tenant.login_policy);
    }
    if (path === `/operator/tenants/${TENANT_ID}/workspaces`) {
      return json([
        {
          id: WORKSPACE_ID,
          slug: "team",
          name: "Synthetic Team",
          tag_ids: [],
          default_mode: "corpus_only",
          default_model: "deepseek-v4.1-flash",
          default_reasoning: false,
        },
      ]);
    }
    if (path === `/operator/tenants/${TENANT_ID}/tags`) {
      return json([{ tag: "alpha-reports", shared: false }]);
    }
    if (path === `/operator/tenants/${TENANT_ID}/workspaces/${WORKSPACE_ID}/tags`) {
      return json({ detail: "tag_not_in_package" }, 422);
    }
    return json({ detail: "not_found" }, 404);
  });
}

test("the console and the chat app link to each other, and terminated tenants show", async ({
  page,
}) => {
  const calls: { method: string; path: string }[] = [];
  await fakeConsole(page, calls);
  await page.goto("/operator");

  await expect(page.getByTestId("terminated-gone")).toContainText(
    "suspended · purged 23 Oct 2026 · certificate COD-20261023-0000beef",
  );
  await page.getByRole("link", { name: "Chat app" }).click();
  await expect(page.getByRole("heading", { name: "Conversations" })).toBeVisible();
  await page.getByRole("link", { name: "Operator console" }).click();
  await expect(page.getByRole("heading", { name: "Operator console" })).toBeVisible();
});

test("every console save says it was saved, or why not", async ({ page }) => {
  const calls: { method: string; path: string }[] = [];
  await fakeConsole(page, calls);
  await page.goto(`/operator/tenants/${TENANT_ID}?tab=login`);

  await page.getByRole("button", { name: "Save login policy" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved.");
  expect(calls.filter((c) => c.method === "PUT").map((c) => c.path)).toEqual([
    `/operator/tenants/${TENANT_ID}/login-policy`,
  ]);

  await page.getByRole("button", { name: "Workspaces" }).click();
  await page.getByLabel("alpha-reports").check();
  await page.getByRole("button", { name: "Save tags" }).click();
  await expect(page.getByText("Refused (422: tag_not_in_package).")).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(0);
});
