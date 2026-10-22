import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToString } from "react-dom/server";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { OperatorOptions, TenantOut } from "../api/types";
import { tabFrom } from "../lib/operator";
import { OperatorTenant } from "./OperatorTenant";

// Synthetic tenants only (CLAUDE.md).
const tenant = (id: string, slug: string, name: string): TenantOut => ({
  id,
  slug,
  display_name: name,
  verified_domains: [`${slug}.example`],
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
    sso_source_config: {},
    jit_provisioning_enabled: false,
    admin_mfa_required: true,
    sso_endpoints: null,
  } as unknown as TenantOut["login_policy"],
});
const A = tenant("00000000-0000-4000-8000-00000000000a", "alpha", "Synthetic Alpha");
const B = tenant("00000000-0000-4000-8000-00000000000b", "beta", "Synthetic Beta");
const options: OperatorOptions = {
  answer_modes: ["corpus_only", "general_knowledge"],
  models: ["deepseek-v4.1-flash"],
  tags: [],
};

function page(path: string): string {
  const client = new QueryClient();
  client.setQueryData(["operator", "tenants"], [A, B]);
  client.setQueryData(["operator", "tenant", A.id], A);
  client.setQueryData(["operator", "tenant", B.id], B);
  client.setQueryData(["operator", "options"], options);
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/operator/tenants/:tenantId" element={<OperatorTenant />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("OperatorTenant", () => {
  // Phase 1a findings F2: one tenant per page, so a save cannot land on a neighbour.
  it("shows one tenant, and its save button names it", () => {
    const html = page(`/operator/tenants/${B.id}`);
    expect(html).toContain("Synthetic Beta");
    expect(html).toContain("Save entitlements for <!-- -->Synthetic Beta");
    expect(html).not.toContain("Synthetic Alpha");
    expect(html).not.toContain("alpha.example");
  });

  it("opens the tab named in the URL, entitlements otherwise", () => {
    expect(page(`/operator/tenants/${A.id}?tab=login`)).toContain("Save login policy");
    expect(tabFrom("spend")).toBe("spend");
    expect(tabFrom("nonsense")).toBe("entitlements");
    expect(tabFrom(null)).toBe("entitlements");
  });
});
