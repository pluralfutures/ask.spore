import { ApiError } from "../api/client";

// Shared by the operator console pages (P1a-03, P1b-12).
export function errorText(error: unknown): string | null {
  if (error === null || error === undefined) return null;
  return error instanceof ApiError ? `Refused (${error.status}).` : "Something went wrong.";
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
