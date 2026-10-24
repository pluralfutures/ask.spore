import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { WorkspaceFile, WorkspaceSite } from "../api/types";
import { formatDate } from "../lib/format";
import { downloadRefusal, fileAction, typeLabel } from "../lib/files";
import { Button } from "../ui/Button";
import { LINK } from "../ui/link";
import { Notice } from "../ui/Notice";
import { EmptyState, Loading } from "../ui/States";
import { FileText } from "lucide-react";
import { Card } from "../ui/Card";
import { PageHeader } from "../ui/PageHeader";

function save(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

// P1a-14: the files behind a workspace, from the source register, read-only. No search or
// filters in Phase 1a.
export function WorkspaceFiles() {
  const { id = "" } = useParams();
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  const files = useQuery({
    queryKey: ["workspace-files", id],
    queryFn: () => api.workspaceFiles(id),
  });
  const download = useMutation({
    mutationFn: (sourceId: string) => api.download(id, sourceId),
    onSuccess: ({ blob, name }) => save(blob, name),
  });
  const name = workspaces.data?.find((w) => w.id === id)?.name;

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-4">
      <PageHeader
        back={{ to: "/", label: "← Conversations" }}
        title={`Files${name ? ` in ${name}` : ""}`}
      />
      {files.isPending ? <Loading /> : null}
      {files.isError ? <Notice tone="danger">Could not load the files.</Notice> : null}
      {download.error ? (
        <Notice tone="danger" role="alert">
          {downloadRefusal(download.error instanceof ApiError ? download.error.code : null)}
        </Notice>
      ) : null}
      {files.data ? (
        <FileTable
          files={files.data.files}
          busy={download.isPending}
          onDownload={(sourceId) => download.mutate(sourceId)}
        />
      ) : null}
      {files.data?.sites.length ? <SiteList sites={files.data.sites} /> : null}
    </main>
  );
}

export function FileTable({
  files,
  busy,
  onDownload,
}: {
  files: WorkspaceFile[];
  busy: boolean;
  onDownload: (sourceId: string) => void;
}) {
  if (files.length === 0) return <EmptyState title="No files in this workspace." icon={FileText} />;
  // UX-06: the 44 px Download button made this table wider than a phone, so it scrolls
  // sideways in its own box (the page is w-full for that, ahead of UX-10) until UX-09
  // gives tables a stacked mode.
  return (
    <div className="overflow-x-auto">
      <table className="w-full rounded-control bg-surface text-left text-ui">
        <thead>
          <tr>
            <th>Title</th>
            <th>Publisher</th>
            <th>Published</th>
            <th>Added</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {files.map((file) => {
            const action = fileAction(file);
            return (
              <tr key={file.id} data-testid={`file-${file.id}`} className="border-t">
                <td>
                  {file.title} <span className="text-fg-subtle">({typeLabel(file.type)})</span>
                </td>
                <td>{file.publisher}</td>
                <td>{formatDate(file.published_on)}</td>
                <td>{formatDate(file.ingested_on)}</td>
                <td>
                  {action.kind === "download" ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      onClick={() => onDownload(file.id)}
                    >
                      Download
                    </Button>
                  ) : action.kind === "link" ? (
                    <a href={action.href} target="_blank" rel="noreferrer" className={LINK}>
                      View at source
                    </a>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SiteList({ sites }: { sites: WorkspaceSite[] }) {
  return (
    <Card title="Websites" className="text-ui">
      <ul className="divide-y">
        {sites.map((site) => (
          <li key={site.site} className="py-2 first:pt-0 last:pb-0">
            {site.site} · {site.publisher} · {site.page_count}{" "}
            {site.page_count === 1 ? "page" : "pages"} · updated {formatDate(site.last_ingested_on)}
          </li>
        ))}
      </ul>
    </Card>
  );
}
