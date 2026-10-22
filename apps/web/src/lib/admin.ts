import type { AdminUser, Me } from "../api/types";
import { formatDate } from "./format";

// Tenant admin pages (P1a-13): the rules the page applies before calling the API, which
// enforces them again.

export const MAX_RETENTION_DAYS = 30; // CLAUDE.md: chat history retention is 30 days maximum
export const MAX_INSTRUCTIONS_CHARS = 2000;

export function isTenantAdmin(me: Me | null | undefined): boolean {
  return me?.role === "tenant_admin";
}

// A whole number of days from 0 to 30; never more than the 30-day maximum. 0 is "no
// history" (P1b-14): a conversation is kept only while its answer streams.
export function parseRetention(value: string): { days: number } | { error: string } {
  const days = Number(value.trim());
  if (!Number.isInteger(days) || value.trim() === "") return { error: "Enter a number of days." };
  if (days > MAX_RETENTION_DAYS) return { error: "Retention cannot exceed 30 days." };
  if (days < 0) return { error: "Retention cannot be negative." };
  return { days };
}

export function retentionSummary(days: number): string {
  if (days === 0) return "No history: each conversation is deleted as soon as its answer ends.";
  return `Conversations are deleted ${days} day${days === 1 ? "" : "s"} after they start.`;
}

const METHODS: Record<string, string> = { sign_in_link: "sign-in link" };

export function lastLogin(user: AdminUser): string {
  if (!user.last_login_at) return "Never signed in";
  const method = user.last_login_method ? METHODS[user.last_login_method] : null;
  return method ? `${formatDate(user.last_login_at)} · ${method}` : formatDate(user.last_login_at);
}

// An admin cannot change their own role or status (the API refuses it too).
export function userActions(user: AdminUser, selfEmail: string | undefined) {
  const self = user.email === selfEmail;
  return {
    canChangeRole: !self,
    canDeactivate: !self && user.status !== "deactivated",
    canReactivate: !self && user.status === "deactivated",
  };
}

const REFUSALS: Record<string, string> = {
  domain_not_verified:
    "Only addresses on your organisation's verified email domains can be invited.",
  email_taken: "That address already has an account.",
  invalid_email: "That is not an email address.",
  cannot_change_self: "You cannot change your own role or status.",
  model_not_enabled: "That model is not enabled for your organisation.",
  external_not_entitled: "That model is not enabled for your organisation.",
  model_unavailable: "That model is not available.",
  reasoning_unsupported: "That model cannot reason; switch reasoning off.",
  mode_not_enabled: "That answer mode is not enabled for your organisation.",
  concurrent_save: "Someone else saved at the same time; reload and try again.",
};

export function adminRefusal(code: string | null): string {
  return (code && REFUSALS[code]) || "The change was refused.";
}
