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

// P2A-06: the notice version a user accepted, and whether it is the active one.
export function consentStatus(user: AdminUser): string {
  if (!user.consent_version) return "Not accepted";
  return user.consent_current
    ? `${user.consent_version} (current)`
    : `${user.consent_version} (older notice)`;
}

export function usersHeading(noticeVersion: string | undefined): string {
  return noticeVersion ? `Users · notice ${noticeVersion}` : "Users";
}

// An admin cannot change their own role or status, nor remove themselves (the API
// refuses it too). P1c-07: an invitation can be sent again while the user is invited.
export function userActions(user: AdminUser, selfEmail: string | undefined) {
  const self = user.email === selfEmail;
  return {
    canChangeRole: !self,
    canDeactivate: !self && user.status !== "deactivated",
    canReactivate: !self && user.status === "deactivated",
    canResend: user.status === "invited",
    canRemove: !self,
  };
}

const REFUSALS: Record<string, string> = {
  domain_not_verified:
    "Only addresses on your organisation's verified email domains can be invited.",
  email_taken: "That address already has an account.",
  invalid_email: "That is not an email address.",
  cannot_change_self: "You cannot change your own role or status.",
  // P1c-07: resend and remove.
  not_invited: "This user has already signed in; there is no invitation to send again.",
  cannot_remove_self: "You cannot remove yourself.",
  last_admin: "The organisation's last admin cannot be removed. Make another user admin first.",
  platform_role: "This user holds an operator or content role; revoke it first.",
  register_author: "This user is named in the source register and cannot be removed.",
  provider_not_updated: "The sign-in service could not be updated; nothing was removed.",
  unknown_user_table: "Removal is not available until the platform is updated.",
  model_not_enabled: "That model is not enabled for your organisation.",
  external_not_entitled: "That model is not enabled for your organisation.",
  model_unavailable: "That model is not available.",
  reasoning_unsupported: "That model cannot reason; switch reasoning off.",
  mode_not_enabled: "That answer mode is not enabled for your organisation.",
  concurrent_save: "Someone else saved at the same time; reload and try again.",
  // P2A-07: the audit export.
  rate_limited: "One export a minute: wait a minute and download again.",
  invalid_period: "The start date must be on or before the end date.",
  invalid_cursor: "Start the download again from the first part.",
};

// P2A-07: the export's query string, with the chosen dates and the next part's cursor.
export function auditLogQuery(since: string, until: string, after?: string | null): string {
  const params = new URLSearchParams();
  if (since) params.set("since", since);
  if (until) params.set("until", until);
  if (after) params.set("after", after);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

// The form's defaults: the last 90 days, as the API's.
export function defaultAuditPeriod(today: Date = new Date()): { since: string; until: string } {
  const since = new Date(today.getTime());
  since.setUTCDate(since.getUTCDate() - 90);
  return { since: isoDay(since), until: isoDay(today) };
}

export function adminRefusal(code: string | null): string {
  return (code && REFUSALS[code]) || "The change was refused.";
}
