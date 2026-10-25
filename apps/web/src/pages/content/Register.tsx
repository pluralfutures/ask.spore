import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { contentApi, type SourceFilters } from "../../api/client";
import type { ContentSource } from "../../api/types";
import { SOURCE_STATUSES, SOURCE_TYPES, errorMessage, filtersFromSearch } from "../../lib/content";
import { formatDate } from "../../lib/format";
import { LINK } from "../../ui/link";
import { Field } from "../../ui/Field";
import { Input, Select } from "../../ui/Input";
import { Notice } from "../../ui/Notice";
import { cardClass } from "../../ui/cardClass";
import { SearchX } from "lucide-react";
import { Badge, StatusBadge } from "../../ui/Badge";
import { EmptyState, Skeleton } from "../../ui/States";
import { Table, Td, Th } from "../../ui/Table";

// The source register with filters by status, tag, type and publisher (P1b-05). P2A-04: a
// link may carry them (the operator console links a workspace's tags here).
export function Register() {
  const location = useLocation();
  const [filters, setFilters] = useState<SourceFilters>(() => filtersFromSearch(location.search));
  const tags = useQuery({ queryKey: ["content", "tags"], queryFn: contentApi.tags });
  const sources = useQuery({
    queryKey: ["content", "sources", filters],
    queryFn: () => contentApi.sources(filters),
  });
  const set = (key: keyof SourceFilters) => (value: string) =>
    setFilters({
      ...filters,
      [key]: value || undefined,
      // Choosing one tag replaces the workspace's set.
      ...(key === "tag" ? { tags: undefined } : {}),
    });
  return (
    <section className="flex flex-col gap-3">
      {/* UX-21: the filter bar on the form components, one row from 768 px. */}
      <div role="search" className={cardClass("grid grid-cols-2 items-end gap-3 md:grid-cols-4")}>
        <FilterSelect
          label="Status"
          value={filters.status}
          options={SOURCE_STATUSES}
          onChange={set("status")}
        />
        <FilterSelect
          label="Tag"
          value={filters.tag}
          options={tags.data?.map((t) => t.tag) ?? []}
          onChange={set("tag")}
        />
        <FilterSelect
          label="Type"
          value={filters.type}
          options={SOURCE_TYPES}
          onChange={set("type")}
        />
        <Field label="Publisher">
          <Input
            value={filters.publisher ?? ""}
            onChange={(e) => set("publisher")(e.target.value)}
          />
        </Field>
      </div>
      {filters.tags?.length ? (
        <Notice tone="info" data-testid="workspace-tags">
          Sources in the tags {filters.tags.join(", ")}.{" "}
          <button type="button" className={LINK} onClick={() => set("tag")("")}>
            Show every tag
          </button>
        </Notice>
      ) : null}
      {errorMessage(sources.error) ? (
        <Notice tone="danger">{errorMessage(sources.error)}</Notice>
      ) : null}
      {sources.data ? <SourceTable sources={sources.data} /> : <Skeleton />}
    </section>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string | undefined;
  options: readonly string[];
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label}>
      <Select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">any</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </Select>
    </Field>
  );
}

export function SourceTable({ sources }: { sources: ContentSource[] }) {
  if (sources.length === 0) return <EmptyState title="No sources match." icon={SearchX} />;
  return (
    <Table>
      <thead>
        <tr>
          <Th>Title</Th>
          <Th>Publisher</Th>
          <Th>Type</Th>
          <Th>Tags</Th>
          <Th>Status</Th>
          <Th>Updated</Th>
        </tr>
      </thead>
      <tbody>
        {sources.map((source) => (
          <tr key={source.id}>
            <Td label="Title">
              <Link to={`/content/sources/${source.id}`} className={LINK}>
                {source.title}
              </Link>
              {source.possible_replacement ? (
                <Badge tone="warning" data-testid={`replacement-${source.id}`} className="ml-2">
                  possible replacement
                </Badge>
              ) : null}
              {source.site_id ? (
                <span className="ml-2 text-meta text-fg-subtle">web page</span>
              ) : null}
            </Td>
            <Td label="Publisher">{source.publisher}</Td>
            <Td label="Type" className="uppercase">
              {source.type}
            </Td>
            <Td label="Tags">{source.tags.join(", ")}</Td>
            <Td label="Status">
              <StatusBadge kind="source" status={source.status} />
              {source.takedown_due_on && source.status !== "withdrawn" ? (
                <Badge tone="danger" className="ml-1">
                  takedown
                </Badge>
              ) : null}
            </Td>
            <Td label="Updated">{formatDate(source.updated_at)}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
