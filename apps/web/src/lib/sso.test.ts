import { describe, expect, it } from "vitest";

import type { LoginPolicyOut } from "../api/types";
import { emptySourceForm, policySummary, sourceBody, ssoButtonLabel } from "./sso";

const TENANT_ID = "0b1c2d3e-4f50-4617-8899-aabbccddeeff";

describe("sourceBody", () => {
  it("builds an Entra source and leaves an empty secret out", () => {
    const form = {
      ...emptySourceForm("entra"),
      entraTenantId: TENANT_ID,
      clientId: " app-1 ",
      adminGroupIds: `${TENANT_ID}, `,
    };
    expect(sourceBody(form)).toEqual({
      body: {
        kind: "entra",
        entra_tenant_id: TENANT_ID,
        client_id: "app-1",
        admin_group_ids: [TENANT_ID],
      },
    });
    expect(sourceBody({ ...form, clientSecret: "s3cret" })).toMatchObject({
      body: { client_secret: "s3cret" },
    });
  });

  it("refuses what the API would refuse", () => {
    expect(sourceBody({ ...emptySourceForm("entra"), clientId: "x" })).toEqual({
      error: "Entra tenant ID must be a UUID.",
    });
    expect(
      sourceBody({ ...emptySourceForm("oidc"), clientId: "x", issuer: "http://idp.example" }),
    ).toEqual({ error: "Issuer must be https." });
    expect(sourceBody(emptySourceForm("saml"))).toEqual({
      error: "Paste the IdP's SAML metadata.",
    });
    expect(sourceBody(emptySourceForm("google"))).toEqual({ error: "Client ID is required." });
  });

  it("sends SAML metadata as given", () => {
    expect(sourceBody({ ...emptySourceForm("saml"), metadataXml: "<x/>" })).toEqual({
      body: { kind: "saml", metadata_xml: "<x/>" },
    });
  });
});

describe("policySummary", () => {
  it("lists the non-secret fields and the endpoints for the client's IT", () => {
    const policy: LoginPolicyOut = {
      sign_in_links_enabled: false,
      sso_source_kind: "entra",
      sso_source_slug: "sso-synthetic",
      sso_source_config: { entra_tenant_id: TENANT_ID, admin_group_ids: [] },
      jit_provisioning_enabled: true,
      admin_mfa_required: true,
      updated_at: "2026-10-21T10:00:00Z",
      sso_endpoints: { redirect_uri: "https://host.example/source/oauth/callback/sso-x/" },
    };
    expect(policySummary(policy)).toEqual([
      ["Single sign-on", "Microsoft Entra ID"],
      ["Sign-in links", "off"],
      ["Create users on first SSO sign-in", "on"],
      ["Second factor for tenant admins", "required"],
      ["entra_tenant_id", TENANT_ID],
      ["admin_group_ids", "none"],
      ["redirect_uri", "https://host.example/source/oauth/callback/sso-x/"],
    ]);
  });
});

describe("ssoButtonLabel", () => {
  it("names the IdP", () => {
    expect(ssoButtonLabel("entra")).toBe("Continue with Microsoft");
    expect(ssoButtonLabel("google")).toBe("Continue with Google");
    expect(ssoButtonLabel("saml")).toBe("Continue with your organisation's sign-in");
  });
});
