import type { WorkspaceSummary } from "../api/types";
import { formatDate } from "./format";

// P2B-05: the wording of the home page's "Sources in this workspace" card, approved by the
// owner on Oct 27, 2026 (phase-2b-build-spec.md, P2B-05).

export const SUMMARY_HEADING = "Sources in this workspace";
export const SUMMARY_EMPTY = "No documents have been added to this workspace yet.";

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export function countLine(summary: WorkspaceSummary): string {
  return (
    `${plural(summary.document_count, "document", "documents")} from ` +
    plural(summary.publisher_count, "publisher", "publishers")
  );
}

// Three or fewer publishers are all named; more are "Including" the three largest.
export function publishersLine(summary: WorkspaceSummary): string | null {
  const shown = summary.top_publishers;
  if (shown.length === 0) return null;
  const more = summary.publisher_count - shown.length;
  return more > 0 ? `Including ${shown.join(", ")} and ${more} more` : `From ${joinNames(shown)}`;
}

export function yearsLine(summary: WorkspaceSummary): string | null {
  const { first_year: first, last_year: last } = summary;
  if (first == null || last == null) return null;
  return first === last ? `Published in ${first}` : `Published ${first} to ${last}`;
}

export function updatedLine(summary: WorkspaceSummary): string | null {
  return summary.last_updated ? `Last updated ${formatDate(summary.last_updated)}` : null;
}
