import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { WorkspaceFile, WorkspaceSite } from "../api/types";
import { formatDate } from "../lib/format";
import { downloadRefusal, fileAction, typeLabel } from "../lib/files";

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
    <main className="mx-auto flex max-w-4xl flex-col gap-4 p-4">
      <Link to="/" className="text-ui underline">
        ← Conversations
      </Link>
      <h1 className="text-title font-strong">Files{name ? ` in ${name}` : ""}</h1>
      {files.isPending ? <p>Loading…</p> : null}
      {files.isError ? <p className="text-danger">Could not load the files.</p> : null}
      {download.error ? (
        <p role="alert" className="text-danger">
          {downloadRefusal(download.error instanceof ApiError ? download.error.code : null)}
        </p>
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
  if (files.length === 0) return <p className="text-fg-muted">No files in this workspace.</p>;
  return (
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
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onDownload(file.id)}
                    className="underline"
                  >
                    Download
                  </button>
                ) : action.kind === "link" ? (
                  <a href={action.href} target="_blank" rel="noreferrer" className="underline">
                    View at source
                  </a>
                ) : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SiteList({ sites }: { sites: WorkspaceSite[] }) {
  return (
    <section className="text-ui">
      <h2 className="mb-1 font-strong">Websites</h2>
      <ul className="rounded-control bg-surface">
        {sites.map((site) => (
          <li key={site.site} className="border-t p-2 first:border-t-0">
            {site.site} · {site.publisher} · {site.page_count}{" "}
            {site.page_count === 1 ? "page" : "pages"} · updated {formatDate(site.last_ingested_on)}
          </li>
        ))}
      </ul>
    </section>
  );
}
