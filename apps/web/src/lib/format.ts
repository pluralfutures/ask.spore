const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

export function formatDate(value: string | null | undefined): string {
  if (!value) return "undated";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "undated" : DATE.format(date);
}

export function pageLabel(type: string, page: number | null): string | null {
  if (page === null) return null;
  return type === "pptx" ? `slide ${page}` : `p. ${page}`;
}

const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

// P2A-08: when a support grant starts and ends, in the viewer's time zone.
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "–";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "–" : DATE_TIME.format(date);
}
