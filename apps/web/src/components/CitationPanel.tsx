import { X } from "lucide-react";

import type { Citation } from "../api/types";
import { CITATION_STATUS_NOTE, EXCERPT_REMOVED_NOTE, citationStatus } from "../lib/citations";
import { formatDate, pageLabel } from "../lib/format";
import { IconButton } from "../ui/IconButton";
import { LINK } from "../ui/link";

interface Props {
  citations: Citation[];
  selected: number;
  onClose: () => void;
}

export function CitationPanel({ citations, selected, onClose }: Props) {
  return (
    <aside
      aria-label="Citations"
      className="w-full shrink-0 overflow-y-auto border-l bg-surface-subtle p-4 md:w-96"
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-strong">Sources</h2>
        <IconButton label="Close" icon={X} size="sm" onClick={onClose} />
      </div>
      <ol className="space-y-3">
        {citations.map((c) => {
          const page = pageLabel(c.type, c.page_or_slide);
          const status = citationStatus(c);
          return (
            <li
              key={c.marker}
              data-testid={`citation-${c.marker}`}
              aria-current={c.marker === selected ? "true" : undefined}
              className={`rounded-control border bg-surface p-3 text-ui ${
                c.marker === selected ? "border-selected ring-1 ring-selected" : ""
              }`}
            >
              <p className="font-emphasis">
                [{c.marker}] {c.title}
                {status ? (
                  <span
                    data-testid={`citation-status-${c.marker}`}
                    title={CITATION_STATUS_NOTE[status]}
                    className="ml-2 rounded-control bg-warning-muted px-1.5 py-0.5 text-meta font-normal text-warning"
                  >
                    {status}
                  </span>
                ) : null}
              </p>
              {status ? (
                <p className="text-meta text-warning">{CITATION_STATUS_NOTE[status]}</p>
              ) : null}
              <p className="text-fg-muted">
                {c.publisher} · {formatDate(c.published_on)}
                {page ? ` · ${page}` : ""}
              </p>
              {c.excerpt ? (
                <blockquote className="mt-2 border-l-2 pl-2 text-fg-secondary">
                  {c.excerpt}
                </blockquote>
              ) : (
                <p data-testid={`citation-no-excerpt-${c.marker}`} className="mt-2 text-fg-subtle">
                  {EXCERPT_REMOVED_NOTE}
                </p>
              )}
              {c.canonical_url ? (
                <a
                  href={c.canonical_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`mt-2 inline-block ${LINK}`}
                >
                  View at source
                </a>
              ) : null}
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
