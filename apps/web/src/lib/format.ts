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
