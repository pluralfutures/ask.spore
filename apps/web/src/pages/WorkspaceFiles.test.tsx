import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { WorkspaceFile } from "../api/types";
import { downloadRefusal, fileAction } from "../lib/files";
import { FileTable } from "./WorkspaceFiles";

// Synthetic register rows only (CLAUDE.md).
const file = (extra: Partial<WorkspaceFile> = {}): WorkspaceFile => ({
  id: "33333333-3333-4333-8333-333333333333",
  type: "pdf",
  title: "Synthetic Outlook 2026",
  publisher: "Synthetic Institute",
  published_on: "2026-03-01",
  canonical_url: "https://example.org/synthetic-outlook",
  ingested_on: "2026-10-19",
  downloadable: false,
  ...extra,
});

describe("file actions", () => {
  it("offers a download only when the register allows it", () => {
    expect(fileAction(file({ downloadable: true }))).toEqual({ kind: "download" });
    expect(fileAction(file())).toEqual({
      kind: "link",
      href: "https://example.org/synthetic-outlook",
    });
    expect(fileAction(file({ canonical_url: null }))).toEqual({ kind: "none" });
  });

  it("explains the daily cap", () => {
    expect(downloadRefusal("download_cap_reached")).toContain("today's download limit");
  });
});

describe("FileTable", () => {
  it("shows the register fields, a download button or the canonical link", () => {
    const html = renderToString(
      <FileTable
        files={[
          file({ id: "a", downloadable: true }),
          file({ id: "b", title: "Synthetic Deck", type: "pptx" }),
        ]}
        busy={false}
        onDownload={() => {}}
      />,
    );
    expect(html).toContain("Synthetic Outlook 2026");
    expect(html).toContain("Synthetic Institute");
    expect(html).toContain("1 Mar 2026");
    expect(html).toContain("19 Oct 2026");
    expect(html.match(/<button/g)).toHaveLength(1);
    expect(html).toContain('href="https://example.org/synthetic-outlook"');
    expect(html).toContain("PPTX");
  });
});
