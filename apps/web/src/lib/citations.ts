// Inline citation markers: "[n]" in an answer refers to citation n of that message.
// The API already drops markers that reference nothing; markers without a matching
// citation (for example while the answer is still streaming) stay plain text.

const MARKER = /\[(\d{1,3})\]/g;
export const CITE_HREF_PREFIX = "#cite-";

export type Segment = { kind: "text"; text: string } | { kind: "marker"; marker: number };

/** Split text into plain text and citation markers whose number is in `valid`. */
export function splitMarkers(text: string, valid: ReadonlySet<number>): Segment[] {
  const segments: Segment[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    const marker = Number(match[1]);
    if (!valid.has(marker)) continue;
    const start = match.index;
    if (start > last) segments.push({ kind: "text", text: text.slice(last, start) });
    segments.push({ kind: "marker", marker });
    last = start + match[0].length;
  }
  if (last < text.length) segments.push({ kind: "text", text: text.slice(last) });
  return segments;
}

/** Markdown with each valid marker turned into a link to `#cite-n`, rendered as a button. */
export function linkMarkers(markdown: string, valid: ReadonlySet<number>): string {
  return splitMarkers(markdown, valid)
    .map((s) =>
      s.kind === "text" ? s.text : `[\\[${s.marker}\\]](${CITE_HREF_PREFIX}${s.marker})`,
    )
    .join("");
}

/** The marker number of a `#cite-n` link, or null for any other href. */
export function markerFromHref(href: string | undefined): number | null {
  if (!href?.startsWith(CITE_HREF_PREFIX)) return null;
  const n = Number(href.slice(CITE_HREF_PREFIX.length));
  return Number.isInteger(n) && n > 0 ? n : null;
}

/** What happened to a cited source since the answer (P1b-03): withdrawn wins over superseded. */
export type CitationStatus = "withdrawn" | "superseded" | null;

export function citationStatus(c: { superseded?: boolean; withdrawn?: boolean }): CitationStatus {
  if (c.withdrawn) return "withdrawn";
  if (c.superseded) return "superseded";
  return null;
}

export const CITATION_STATUS_NOTE: Record<Exclude<CitationStatus, null>, string> = {
  withdrawn: "This source has been withdrawn from the research package since this answer.",
  superseded: "A newer version of this source has replaced the one this answer quoted.",
};
