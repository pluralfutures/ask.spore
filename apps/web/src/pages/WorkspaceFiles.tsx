import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { WorkspaceFile, WorkspaceSite } from "../api/types";
import { formatDate } from "../lib/format";
import { downloadRefusal, fileAction, typeLabel } from "../lib/files";
import { Button } from "../ui/Button";
import { NewTabLink } from "../ui/NewTabLink";
import { Notice } from "../ui/Notice";
import { EmptyState, Skeleton } from "../ui/States";
import { Download, FileText } from "lucide-react";
import { PageHeader } from "../ui/PageHeader";
import { CONVERSATIONS_PATH } from "./ConversationList";
import { ActionsTh, Table, Td, Th } from "../ui/Table";

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
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-4 md:px-8 md:py-6">
      <PageHeader
        back={{ to: CONVERSATIONS_PATH, label: "← Conversations" }}
        title={`Files${name ? ` in ${name}` : ""}`}
      />
      {files.isPending ? <Skeleton /> : null}
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
    </div>
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
  return (
    <Table>
      <thead>
        <tr>
          <Th>Title</Th>
          <Th>Publisher</Th>
          <Th>Published</Th>
          <Th>Added</Th>
          <ActionsTh />
        </tr>
      </thead>
      <tbody>
        {files.map((file) => {
          const action = fileAction(file);
          return (
            <tr key={file.id} data-testid={`file-${file.id}`}>
              <Td label="Title">
                <span className="font-emphasis">{file.title}</span>{" "}
                <span className="text-meta text-fg-subtle">({typeLabel(file.type)})</span>
              </Td>
              <Td label="Publisher">{file.publisher}</Td>
              <Td label="Published">{formatDate(file.published_on)}</Td>
              <Td label="Added">{formatDate(file.ingested_on)}</Td>
              <Td>
                {action.kind === "download" ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={Download}
                    disabled={busy}
                    onClick={() => onDownload(file.id)}
                  >
                    Download
                  </Button>
                ) : action.kind === "link" ? (
                  <NewTabLink href={action.href} className="whitespace-nowrap">
                    View at source
                  </NewTabLink>
                ) : null}
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

// UX-17: the crawled websites as a second table.
function SiteList({ sites }: { sites: WorkspaceSite[] }) {
  return (
    <section aria-labelledby="websites" className="flex flex-col gap-3">
      <h2 id="websites" className="text-heading font-strong">
        Websites
      </h2>
      <Table>
        <thead>
          <tr>
            <Th>Site</Th>
            <Th>Publisher</Th>
            <Th numeric>Pages</Th>
            <Th>Updated</Th>
          </tr>
        </thead>
        <tbody>
          {sites.map((site) => (
            <tr key={site.site} data-testid={`site-${site.site}`}>
              <Td label="Site">
                <span className="font-emphasis">{site.site}</span>
              </Td>
              <Td label="Publisher">{site.publisher}</Td>
              <Td label="Pages" numeric>
                {site.page_count} {site.page_count === 1 ? "page" : "pages"}
              </Td>
              <Td label="Updated">{formatDate(site.last_ingested_on)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </section>
  );
}
