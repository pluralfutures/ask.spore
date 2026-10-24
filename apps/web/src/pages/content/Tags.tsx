import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { contentApi } from "../../api/client";
import type { ContentTag } from "../../api/types";
import { canReview, errorMessage } from "../../lib/content";
import { Button } from "../../ui/Button";
import { LINK } from "../../ui/link";
import { Notice } from "../../ui/Notice";
import { Loading } from "../../ui/States";
import { Badge } from "../../ui/Badge";
import { Table, Td, Th } from "../../ui/Table";

// Tag management (P1b-05): the tags of config/tags.toml and their RAGFlow datasets.
// Tags are edited in that file (a reviewed change); the page shows the mapping and a
// reviewer syncs it (creates or adopts each tag's dataset), audited.
export function Tags({ roles }: { roles: string[] }) {
  const queryClient = useQueryClient();
  const tags = useQuery({ queryKey: ["content", "tags"], queryFn: contentApi.tags });
  const sync = useMutation({
    mutationFn: contentApi.syncTags,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["content", "tags"] }),
  });
  return (
    <section className="flex flex-col gap-3">
      <p className="text-fg-muted">
        Tags live in config/tags.toml; change them there. A sync creates the dataset of a new tag in
        RAGFlow.
      </p>
      {canReview(roles) ? (
        <Button
          variant="secondary"
          className="w-fit"
          onClick={() => sync.mutate()}
          disabled={sync.isPending}
        >
          Sync datasets
        </Button>
      ) : null}
      {sync.data ? (
        <p data-testid="sync-result">{sync.data.map((r) => `${r.tag}: ${r.status}`).join(" · ")}</p>
      ) : null}
      {errorMessage(sync.error) ? <Notice tone="danger">{errorMessage(sync.error)}</Notice> : null}
      {tags.data ? <TagTable tags={tags.data} /> : <Loading />}
    </section>
  );
}

export function TagTable({ tags }: { tags: ContentTag[] }) {
  return (
    <Table>
      <thead>
        <tr>
          <Th>Tag</Th>
          <Th>Chunking</Th>
          <Th>Dataset</Th>
          <Th numeric>Ingested sources</Th>
        </tr>
      </thead>
      <tbody>
        {tags.map((tag) => (
          <tr key={tag.tag}>
            <Td label="Tag">{tag.tag}</Td>
            <Td label="Chunking">
              {tag.chunk_method}
              {Object.entries(tag.chunk_method_by_type).map(
                ([type, method]) => ` · ${type}: ${method}`,
              )}
            </Td>
            <Td label="Dataset">
              {tag.dataset_id === null ? (
                <Badge tone="warning">not synced</Badge>
              ) : tag.ragflow_url ? (
                <a
                  href={tag.ragflow_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={LINK}
                >
                  {tag.dataset_id}
                </a>
              ) : (
                tag.dataset_id
              )}
            </Td>
            <Td label="Ingested sources" numeric>
              {tag.sources}
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
