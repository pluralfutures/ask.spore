import type { LoginPolicyOut, SsoSourceIn } from "../api/types";

// Client SSO (P1b-07): how the sign-in page names a source, the operator's source form,
// and the read-only summary the tenant admin page shows.
export type SsoKind = "entra" | "google" | "oidc" | "saml";

export function ssoButtonLabel(kind: SsoKind | null): string {
  if (kind === "entra") return "Continue with Microsoft";
  if (kind === "google") return "Continue with Google";
  return "Continue with your organisation's sign-in";
}

export interface SourceForm {
  kind: SsoKind;
  clientId: string;
  clientSecret: string;
  entraTenantId: string;
  adminGroupIds: string;
  issuer: string;
  metadataXml: string;
}

export function emptySourceForm(kind: SsoKind = "entra"): SourceForm {
  return {
    kind,
    clientId: "",
    clientSecret: "",
    entraTenantId: "",
    adminGroupIds: "",
    issuer: "",
    metadataXml: "",
  };
}

// P1c-02: after "Remove SSO source" the form forgets the removed source's kind, issuer,
// client ID and the rest (Phase 1b release 2.4: it kept them while the summary said none).
export function formAfterRemoval(): SourceForm {
  return emptySourceForm();
}

interface SourceActionState {
  isSuccess: boolean;
  error: unknown;
  submittedAt: number;
}

// P1c-08 (Phase 1c release F2): the source form shows the status of its latest action only,
// so "SSO source removed." does not stay under a later "Saved." (and the reverse).
export function latestSourceAction(
  save: SourceActionState,
  remove: SourceActionState,
): { isSuccess: boolean; error: unknown; savedText: string } {
  if (remove.submittedAt > save.submittedAt) {
    return { isSuccess: remove.isSuccess, error: remove.error, savedText: "SSO source removed." };
  }
  return { isSuccess: save.isSuccess, error: save.error, savedText: "Saved." };
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// The request for PUT /operator/tenants/{id}/login-policy/sso. An empty secret is left
// out, so Authentik keeps the one it holds (the API asks for it when it is needed).
export function sourceBody(form: SourceForm): { body: SsoSourceIn } | { error: string } {
  const secret = form.clientSecret.trim() ? { client_secret: form.clientSecret.trim() } : {};
  const clientId = form.clientId.trim();
  if (form.kind === "saml") {
    if (!form.metadataXml.trim()) return { error: "Paste the IdP's SAML metadata." };
    return { body: { kind: "saml", metadata_xml: form.metadataXml } };
  }
  if (!clientId) return { error: "Client ID is required." };
  if (form.kind === "google") return { body: { kind: "google", client_id: clientId, ...secret } };
  if (form.kind === "oidc") {
    if (!form.issuer.trim().startsWith("https://")) return { error: "Issuer must be https." };
    return { body: { kind: "oidc", issuer: form.issuer.trim(), client_id: clientId, ...secret } };
  }
  const groups = form.adminGroupIds
    .split(",")
    .map((g) => g.trim())
    .filter(Boolean);
  if (!UUID.test(form.entraTenantId.trim())) return { error: "Entra tenant ID must be a UUID." };
  if (groups.some((g) => !UUID.test(g))) return { error: "Admin groups must be object IDs." };
  return {
    body: {
      kind: "entra",
      entra_tenant_id: form.entraTenantId.trim(),
      client_id: clientId,
      admin_group_ids: groups,
      ...secret,
    },
  };
}

const KIND_NAMES: Record<string, string> = {
  none: "none",
  entra: "Microsoft Entra ID",
  google: "Google Workspace",
  oidc: "OpenID Connect",
  saml: "SAML 2.0",
};

// Label and value pairs, non-secret fields only (the API never returns a secret).
export function policySummary(policy: LoginPolicyOut): [string, string][] {
  const rows: [string, string][] = [
    ["Single sign-on", KIND_NAMES[policy.sso_source_kind] ?? policy.sso_source_kind],
    ["Sign-in links", policy.sign_in_links_enabled ? "on" : "off"],
    ["Create users on first SSO sign-in", policy.jit_provisioning_enabled ? "on" : "off"],
    ["Second factor for tenant admins", policy.admin_mfa_required ? "required" : "not required"],
  ];
  for (const [key, value] of Object.entries(policy.sso_source_config)) {
    rows.push([key, Array.isArray(value) ? value.join(", ") || "none" : value]);
  }
  for (const [key, value] of Object.entries(policy.sso_endpoints ?? {})) rows.push([key, value]);
  return rows;
}
