import { ApiError } from "../api/client";
import { adminRefusal } from "./admin";

// The API's refusal codes the console explains in words (P1c-07); any other refusal
// shows its status.
const CONSOLE_REFUSALS: Record<string, string> = {
  email_taken: "That address already has an account, in this or another organisation.",
  domain_taken: "That domain is already verified for another organisation.",
  slug_taken: "That slug is already in use.",
};
const ADMIN_CODES = new Set([
  "invalid_email",
  "not_invited",
  "cannot_remove_self",
  "last_admin",
  "platform_role",
  "register_author",
  "provider_not_updated",
  "unknown_user_table",
]);

// Shared by the operator console pages (P1a-03, P1b-12).
export function errorText(error: unknown): string | null {
  if (error === null || error === undefined) return null;
  if (!(error instanceof ApiError)) return "Something went wrong.";
  const code = error.code ?? "";
  const known = CONSOLE_REFUSALS[code];
  if (known) return known;
  if (ADMIN_CODES.has(code)) return adminRefusal(code);
  return `Refused (${error.status}${code ? `: ${code}` : ""}).`;
}

export function toggle(list: string[], value: string, on: boolean): string[] {
  return on ? [...new Set([...list, value])] : list.filter((v) => v !== value);
}

// The console page's tabs, one tenant at a time (P1b-12).
export const TENANT_TABS = ["entitlements", "login", "workspaces", "users", "spend"] as const;
export type TenantTab = (typeof TENANT_TABS)[number];

export function tabFrom(value: string | null): TenantTab {
  return (TENANT_TABS as readonly string[]).includes(value ?? "")
    ? (value as TenantTab)
    : "entitlements";
}
