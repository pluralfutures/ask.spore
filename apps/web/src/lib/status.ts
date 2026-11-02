// UX-08: which badge tone each status word gets. The word itself is shown unchanged (a
// different word would be copy, which needs the owner's approval); only its colour comes
// from here. An unknown status is neutral.

export type Tone = "neutral" | "accent" | "warning" | "danger" | "success";

export type StatusKind =
  "user" | "tenant" | "source" | "site" | "takedown" | "job" | "page" | "upload";

const TONES: Record<StatusKind, Record<string, Tone>> = {
  user: { active: "success", invited: "accent", deactivated: "neutral" },
  tenant: { active: "success", suspended: "warning", terminating: "danger", terminated: "neutral" },
  source: {
    proposed: "accent",
    approved: "accent",
    ingested: "success",
    failed: "danger",
    withdrawn: "neutral",
    rejected: "neutral",
    paused: "warning",
  },
  site: { proposed: "accent", approved: "success", rejected: "neutral", withdrawn: "neutral" },
  takedown: { open: "warning", done: "success", withdrawn: "neutral" },
  job: { queued: "neutral", running: "accent", succeeded: "success", failed: "danger" },
  page: { live: "success", blocked: "warning", withdrawn: "neutral" },
  // P2SR01: an uploaded crawl's ZIP.
  upload: {
    staged: "accent",
    queued: "accent",
    imported: "success",
    failed: "danger",
    rejected: "neutral",
  },
};

export function statusTone(kind: StatusKind, status: string): Tone {
  return TONES[kind][status] ?? "neutral";
}
