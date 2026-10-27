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
  "paused",
] as const;
export const SOURCE_TYPES = ["pdf", "docx", "pptx", "html", "markdown", "text"] as const;
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

/** P2A-04: the content console's source list filtered by a workspace's tags. */
export function sourcesForTags(tags: readonly string[]): string {
  const params = new URLSearchParams(tags.map((tag) => ["tag", tag]));
  return tags.length ? `/content?${params.toString()}` : "/content";
}

/** The register filters a link carries (the operator console's workspace link). */
export function filtersFromSearch(search: string): {
  status?: string;
  tags?: string[];
  type?: string;
  publisher?: string;
} {
  const params = new URLSearchParams(search);
  const tags = params.getAll("tag").filter(Boolean);
  const one = (key: string) => params.get(key) || undefined;
  return {
    ...(one("status") ? { status: one("status") } : {}),
    ...(tags.length ? { tags } : {}),
    ...(one("type") ? { type: one("type") } : {}),
    ...(one("publisher") ? { publisher: one("publisher") } : {}),
  };
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
  site_withdrawn: "the whole site was withdrawn",
  restored: "restored by a reviewer: taken again at the next crawl",
  reinstated:
    "released when the site was reinstated: taken again at the first crawl after approval",
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
  unsupported_type: "Only PDF, DOCX, PPTX, HTML, Markdown and text files.",
  // P2B-06: a file that is not what its extension says.
  not_text: "The file is not UTF-8 text. A .md or .txt file must be plain UTF-8 text.",
  type_mismatch: "The file does not match its extension or declared type.",
  tdm_reserved: "The page reserves text-and-data-mining rights.",
  no_dataset: "A tag has no dataset yet: sync the tags first.",
  site_exists: "That site is registered already.",
  bad_pattern: "Patterns are paths starting with /, e.g. /reports/*.",
  not_withdrawable: "Only an ingested, paused or failed source can be withdrawn.",
  // P2A-01 to P2A-03: pause and resume.
  not_ingested: "Only an ingested source can be paused.",
  not_paused: "Only a paused source can be resumed.",
  paused: "The source is paused: resume it first.",
  ingestion_in_progress: "An ingestion of this source is running: pause it once it is done.",
  pause_undo_failed:
    "RAGFlow failed part-way and could not be put back: run datasets sync and check the documents.",
  resume_undo_failed:
    "RAGFlow failed part-way and could not be put back: run datasets sync and check the documents.",
  withdrawal_running:
    "The site's pages are still being withdrawn: reinstate it once those jobs have finished.",
  too_large: "The file is too large.",
} as const;
const ERROR_TEXT: Record<string, string | undefined> = ERRORS;

export function errorMessage(error: unknown): string | null {
  if (error === null || error === undefined) return null;
  if (error instanceof ApiError) {
    const known = error.code ? ERROR_TEXT[error.code] : undefined;
    if (known) return known;
    if (error.code?.startsWith("ragflow_"))
      return `RAGFlow refused the change (${error.code}); nothing was changed.`;
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
