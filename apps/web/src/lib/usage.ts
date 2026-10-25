// The tenant admin's usage section (P2A-05): the API sends counts only, for the days
// that had any; the page shows every day of the period, oldest first.
import type { UsageOut } from "../api/types";

export type UsageDay = {
  day: string; // YYYY-MM-DD, UTC
  byMode: Record<string, number>;
  questions: number;
  users: number;
};

export const USAGE_MODE_LABELS: Record<string, string> = {
  corpus_only: "Sources only",
  general_knowledge: "General knowledge",
};

function addDays(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

// One row per UTC day from `since` to `until`, with zeroes where nothing happened.
export function usageDays(usage: UsageOut): UsageDay[] {
  const rows = new Map<string, UsageDay>();
  for (let day = usage.since; day <= usage.until; day = addDays(day, 1)) {
    rows.set(day, { day, byMode: {}, questions: 0, users: 0 });
  }
  for (const q of usage.questions) {
    const row = rows.get(q.day);
    if (!row) continue;
    row.byMode[q.mode] = (row.byMode[q.mode] ?? 0) + q.questions;
    row.questions += q.questions;
  }
  for (const a of usage.active_users) {
    const row = rows.get(a.day);
    if (row) row.users = a.users;
  }
  return [...rows.values()];
}

// The modes that appear in the period, the tenant's usual ones first.
export function usageModes(usage: UsageOut): string[] {
  const seen = new Set(usage.questions.map((q) => q.mode));
  const known = Object.keys(USAGE_MODE_LABELS).filter((m) => seen.has(m));
  return [...known, ...[...seen].filter((m) => !(m in USAGE_MODE_LABELS)).sort()];
}

export function usageTotals(usage: UsageOut): {
  questions: number;
  byMode: Record<string, number>;
  busiestDayUsers: number;
} {
  const byMode: Record<string, number> = {};
  let questions = 0;
  for (const q of usage.questions) {
    byMode[q.mode] = (byMode[q.mode] ?? 0) + q.questions;
    questions += q.questions;
  }
  const busiestDayUsers = usage.active_users.reduce((m, a) => Math.max(m, a.users), 0);
  return { questions, byMode, busiestDayUsers };
}
