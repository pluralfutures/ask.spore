// Content console helpers (P1b-05): labels, the takedown timer, and the proposal form's
// checks, which mirror the API's (the API decides; these only explain early).
import { ApiError } from "../api/client";

export const SOURCE_STATUSES = [
  "proposed",
  "approved",
  "ingested",
  "failed",
  "withdrawn",
  "rejected",
] as const;
export const SOURCE_TYPES = ["pdf", "docx", "pptx", "html", "markdown"] as const;
export const SCHEDULES = ["none", "weekly", "monthly"] as const;
export const LICENCE_BASES = ["public", "open-licence", "publisher-terms", "own-work"];

export const EDITOR = "content_editor";
export const REVIEWER = "content_reviewer";

export function canEdit(roles: readonly string[]): boolean {
  return roles.includes(EDITOR);
}

export function canReview(roles: readonly string[]): boolean {
  return roles.includes(REVIEWER);
}

/** The takedown SLA timer, in working days (negative when overdue). */
export function timerText(days: number): string {
  if (days === 0) return "due today";
  if (days < 0) return `${-days} working day${days === -1 ? "" : "s"} overdue`;
  return `${days} working day${days === 1 ? "" : "s"} left`;
}

export type TimerTone = "overdue" | "due" | "ok";

export function timerTone(days: number): TimerTone {
  if (days < 0) return "overdue";
  return days <= 2 ? "due" : "ok";
}

export const PAGE_REASONS: Record<string, string> = {
  noai_or_noindex: "marked noai or noindex",
  no_content: "no readable content",
  special_category: "special category",
  robots: "disallowed by robots.txt",
  out_of_scope: "outside the scope rules",
  duplicate_content: "same text as another source",
  taken_down: "taken down",
  withdrawn: "withdrawn by a reviewer",
  robots_disallowed: "robots.txt disallows the site",
  tdm_reserved: "the site reserves text-and-data mining",
  http_404: "gone (404)",
  http_410: "gone (410)",
  moved: "moved to another address",
};

export function pageReason(reason: string | null, category: string | null): string {
  if (reason === null) return "";
  const label = PAGE_REASONS[reason] ?? reason;
  return category ? `${label}: ${category.replace(/_/g, " ")}` : label;
}

export const ALLOW_DECISIONS: Record<string, string> = {
  unchecked: "not crawled yet",
  allowed: "allowed (robots.txt and TDM checked)",
  robots_disallowed: "robots.txt disallows us",
  tdm_reserved: "text-and-data mining reserved",
};

const ERRORS = {
  forbidden: "Your content role does not allow this.",
  replacement_choice_required:
    "This file is at the link of an ingested source: choose whether it replaces it, or keep both.",
  not_a_replacement_candidate: "That source is not an ingested source at the same link.",
  replace_or_keep_both: "Choose replace or keep both, not both.",
  file_or_url: "Give either a file or a URL.",
  not_public: "That address is not on the public internet.",
  note_required: "A note is required.",
  unsupported_type: "Only PDF, DOCX, PPTX, HTML and Markdown files.",
  tdm_reserved: "The page reserves text-and-data-mining rights.",
  no_dataset: "A tag has no dataset yet: sync the tags first.",
  site_exists: "That site is registered already.",
  bad_pattern: "Patterns are paths starting with /, e.g. /reports/*.",
  not_withdrawable: "Only an ingested or failed source can be withdrawn.",
  too_large: "The file is too large.",
} as const;
const ERROR_TEXT: Record<string, string | undefined> = ERRORS;

export function errorMessage(error: unknown): string | null {
  if (error === null || error === undefined) return null;
  if (error instanceof ApiError) {
    const known = error.code ? ERROR_TEXT[error.code] : undefined;
    if (known) return known;
    if (error.status === 403) return ERRORS.forbidden;
    return error.code ? `Refused (${error.code}).` : `Refused (${error.status}).`;
  }
  return "Something went wrong.";
}

export interface ProposalFields {
  title: string;
  publisher: string;
  licenceBasis: string;
  tags: string[];
  publishedOn: string;
  canonicalUrl: string;
  downloadable: boolean;
  url: string;
}

export const emptyProposal: ProposalFields = {
  title: "",
  publisher: "",
  licenceBasis: "",
  tags: [],
  publishedOn: "",
  canonicalUrl: "",
  downloadable: false,
  url: "",
};

/** The multipart body of a proposal, or the reason it cannot be sent. */
export function proposalForm(
  fields: ProposalFields,
  file: File | null,
  licence: File | null,
): { form: FormData } | { error: string } {
  const url = fields.url.trim();
  if ((file === null) === (url === "")) return { error: ERRORS.file_or_url };
  if (!fields.title.trim() || !fields.publisher.trim() || !fields.licenceBasis.trim()) {
    return { error: "Title, publisher and licence basis are required." };
  }
  if (fields.tags.length === 0) return { error: "Choose at least one tag." };
  const form = new FormData();
  form.append("title", fields.title.trim());
  form.append("publisher", fields.publisher.trim());
  form.append("licence_basis", fields.licenceBasis.trim());
  for (const tag of fields.tags) form.append("tags", tag);
  if (fields.publishedOn) form.append("published_on", fields.publishedOn);
  if (fields.canonicalUrl.trim()) form.append("canonical_url", fields.canonicalUrl.trim());
  form.append("downloadable", fields.downloadable ? "true" : "false");
  if (file !== null) form.append("file", file);
  else form.append("url", url);
  if (licence !== null) form.append("licence_file", licence);
  return { form };
}

/** One path pattern per line, blank lines dropped. */
export function parsePatterns(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export function historyLine(entry: {
  event: string;
  actor: string | null;
  before: string | null;
  after: string | null;
  method: string | null;
}): string {
  const change =
    entry.before !== entry.after && entry.after
      ? ` (${entry.before ?? "new"} → ${entry.after})`
      : "";
  const who = entry.actor ?? (entry.method === "site_crawl" ? "site crawl" : "system");
  return `${entry.event.replace(/^source\./, "").replace(/_/g, " ")}${change} · ${who}`;
}
