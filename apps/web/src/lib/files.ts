import type { WorkspaceFile } from "../api/types";

// Workspace file list (P1a-14): a file offers a download only when the source register
// allows it; otherwise the row links to the publisher's canonical location.

export type FileAction = { kind: "download" } | { kind: "link"; href: string } | { kind: "none" };

export function fileAction(file: WorkspaceFile): FileAction {
  if (file.downloadable) return { kind: "download" };
  if (file.canonical_url) return { kind: "link", href: file.canonical_url };
  return { kind: "none" };
}

const TYPE_LABELS: Record<string, string> = { pdf: "PDF", docx: "DOCX", pptx: "PPTX" };

export function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type.toUpperCase();
}

const REFUSALS: Record<string, string> = {
  download_cap_reached: "You have reached today's download limit. Try again tomorrow.",
  not_downloadable: "This file cannot be downloaded; use the link to the publisher.",
  file_unavailable: "This file is not available right now.",
};

export function downloadRefusal(code: string | null): string {
  return (code && REFUSALS[code]) || "The download failed.";
}
