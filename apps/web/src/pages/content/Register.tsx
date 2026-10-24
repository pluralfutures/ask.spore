import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { contentApi, type SourceFilters } from "../../api/client";
import type { ContentSource } from "../../api/types";
import { SOURCE_STATUSES, SOURCE_TYPES, errorMessage } from "../../lib/content";
import { formatDate } from "../../lib/format";

// The source register with filters by status, tag, type and publisher (P1b-05).
export function Register() {
  const [filters, setFilters] = useState<SourceFilters>({});
  const tags = useQuery({ queryKey: ["content", "tags"], queryFn: contentApi.tags });
  const sources = useQuery({
    queryKey: ["content", "sources", filters],
    queryFn: () => contentApi.sources(filters),
  });
  const set = (key: keyof SourceFilters) => (value: string) =>
    setFilters({ ...filters, [key]: value || undefined });
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3 rounded-control bg-surface p-3">
        <Select
          label="Status"
          value={filters.status}
          options={SOURCE_STATUSES}
          onChange={set("status")}
        />
        <Select
          label="Tag"
          value={filters.tag}
          options={tags.data?.map((t) => t.tag) ?? []}
          onChange={set("tag")}
        />
        <Select label="Type" value={filters.type} options={SOURCE_TYPES} onChange={set("type")} />
        <label className="flex flex-col">
          Publisher
          <input
            value={filters.publisher ?? ""}
            onChange={(e) => set("publisher")(e.target.value)}
            className="border px-1"
          />
        </label>
      </div>
      {errorMessage(sources.error) ? (
        <p className="text-danger">{errorMessage(sources.error)}</p>
      ) : null}
      {sources.data ? <SourceTable sources={sources.data} /> : <p>Loading…</p>}
    </section>
  );
}

function Select({
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
    <label className="flex flex-col">
      {label}
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} className="border">
        <option value="">any</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

export function SourceTable({ sources }: { sources: ContentSource[] }) {
  if (sources.length === 0) return <p className="text-fg-muted">No sources match.</p>;
  return (
    <table className="w-full rounded-control bg-surface text-left">
      <thead>
        <tr className="border-b">
          <th className="p-2">Title</th>
          <th className="p-2">Publisher</th>
          <th className="p-2">Type</th>
          <th className="p-2">Tags</th>
          <th className="p-2">Status</th>
          <th className="p-2">Updated</th>
        </tr>
      </thead>
      <tbody>
        {sources.map((source) => (
          <tr key={source.id} className="border-b align-top">
            <td className="p-2">
              <Link to={`/content/sources/${source.id}`} className="underline">
                {source.title}
              </Link>
              {source.possible_replacement ? (
                <span
                  data-testid={`replacement-${source.id}`}
                  className="ml-2 rounded-control bg-warning-muted px-1 text-meta text-warning"
                >
                  possible replacement
                </span>
              ) : null}
              {source.site_id ? (
                <span className="ml-2 text-meta text-fg-subtle">web page</span>
              ) : null}
            </td>
            <td className="p-2">{source.publisher}</td>
            <td className="p-2 uppercase">{source.type}</td>
            <td className="p-2">{source.tags.join(", ")}</td>
            <td className="p-2">
              {source.status}
              {source.takedown_due_on && source.status !== "withdrawn" ? (
                <span className="ml-1 text-danger">· takedown</span>
              ) : null}
            </td>
            <td className="p-2">{formatDate(source.updated_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
