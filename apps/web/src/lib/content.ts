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
  not_in_upload: "absent from a full upload of the crawl",
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
  declared: "declared by the uploader (robots.txt, TDM and noai), released by a reviewer",
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
  // P2SR01: uploaded crawls.
  declaration_required: "Tick the declaration: it is the condition of every upload.",
  crawled_in_future: "The crawl date cannot be in the future.",
  upload_pending: "This site has an upload waiting for a reviewer or the worker already.",
  origin_crawl: "This site is crawled by the platform; it takes no uploads.",
  origin_upload: "This site's pages come from uploads; it is never crawled.",
  site_withdrawn: "The site is withdrawn.",
  site_rejected: "The site was rejected.",
  not_staged: "This upload is no longer waiting for a reviewer.",
  not_a_zip: "The file is not a readable ZIP.",
  unsafe_member:
    "The ZIP has an unsafe member (an absolute path, .., a link, an archive or encryption).",
  duplicate_url: "Two files in the ZIP give the same page URL.",
  too_many_members: "The ZIP has more than 2,000 Markdown files.",
  total_too_large: "The ZIP's files come to more than 500 MB uncompressed.",
  no_pages: "No file in the ZIP could be accepted.",
  upload_missing: "The staged ZIP is missing.",
  upload_altered: "The staged ZIP no longer matches what was uploaded.",
} as const;
const ERROR_TEXT: Record<string, string | undefined> = ERRORS;

export function errorMessage(error: unknown): string | null {
  if (error === null || error === undefined) return null;
  if (error instanceof ApiError) {
    const known = error.code ? ERROR_TEXT[error.code] : undefined;
    // P2SR01: a whole-upload refusal names the member by its position in the ZIP.
    if (known && error.member !== null) return `${known} (file ${error.member + 1} in the ZIP)`;
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

// --- P2SR01 uploaded crawls ------------------------------------------------------------

/** The declaration the editor ticks (owner decision 2, Oct 31, 2026), word for word. */
export function declarationText(host: string, crawledOn: string): string {
  return (
    `I confirm that this crawl of ${host || "<host>"} was made on ${crawledOn || "<crawled_on>"} ` +
    "honouring the site's robots.txt, its text-and-data-mining reservation if any, and " +
    "page-level noai and noindex directives, and that the pages are public and were " +
    "fetched without signing in."
  );
}

export function hostOf(url: string): string {
  try {
    return new URL(url.trim()).hostname;
  } catch {
    return "";
  }
}

export const MEMBER_OUTCOMES: Record<string, string> = {
  accepted: "accepted",
  skipped_not_markdown: "skipped: not a Markdown page",
  url_missing: "refused: no Source comment or url key",
  url_mismatch: "refused: the Source comment and the url key disagree",
  bad_url: "refused: not an absolute http(s) URL",
  off_site: "refused: not on the site's host",
  bad_date: "refused: the date is not YYYY-MM-DD",
  front_matter_invalid: "refused: the front matter cannot be read",
  empty: "refused: no text after the front matter",
  not_utf8: "refused: not UTF-8 text",
  member_too_large: "refused: larger than 5 MB",
};

export const MEMBER_NOTES: Record<string, string> = {
  special_category: "will be blocked: special category",
  out_of_scope: "will be blocked: outside the scope rules",
};

export interface UploadFields {
  crawledOn: string;
  mode: "full" | "partial";
  declared: boolean;
  startUrl: string;
  name: string;
  publisher: string;
  licenceBasis: string;
  tags: string[];
}

export const emptyUpload: UploadFields = {
  crawledOn: "",
  mode: "partial",
  declared: false,
  startUrl: "",
  name: "",
  publisher: "",
  licenceBasis: "",
  tags: [],
};

/** The multipart body of an upload, or the reason it cannot be sent. ``newSite``: the
 * upload registers its site too. */
export function uploadForm(
  fields: UploadFields,
  file: File | null,
  newSite: boolean,
): { form: FormData } | { error: string } {
  if (file === null) return { error: "Choose the ZIP of the crawl." };
  if (!fields.crawledOn) return { error: "Give the crawl date." };
  if (!fields.declared) return { error: ERRORS.declaration_required };
  const form = new FormData();
  if (newSite) {
    if (
      !fields.startUrl.trim() ||
      !fields.name.trim() ||
      !fields.publisher.trim() ||
      !fields.licenceBasis.trim()
    ) {
      return { error: "Start URL, name, publisher and licence basis are required." };
    }
    if (fields.tags.length === 0) return { error: "Choose at least one tag." };
    form.append("start_url", fields.startUrl.trim());
    form.append("name", fields.name.trim());
    form.append("publisher", fields.publisher.trim());
    form.append("licence_basis", fields.licenceBasis.trim());
    for (const tag of fields.tags) form.append("tags", tag);
  }
  form.append("crawled_on", fields.crawledOn);
  form.append("mode", fields.mode);
  form.append("declared_robots_honoured", "true");
  form.append("file", file);
  return { form };
}
