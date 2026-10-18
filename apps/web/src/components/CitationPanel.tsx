import type { Citation } from "../api/types";
import { formatDate, pageLabel } from "../lib/format";

interface Props {
  citations: Citation[];
  selected: number;
  onClose: () => void;
}

export function CitationPanel({ citations, selected, onClose }: Props) {
  return (
    <aside
      aria-label="Citations"
      className="w-full shrink-0 overflow-y-auto border-l bg-slate-50 p-4 md:w-96"
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold">Sources</h2>
        <button type="button" onClick={onClose} className="text-sm underline">
          Close
        </button>
      </div>
      <ol className="space-y-3">
        {citations.map((c) => {
          const page = pageLabel(c.type, c.page_or_slide);
          return (
            <li
              key={c.marker}
              data-testid={`citation-${c.marker}`}
              aria-current={c.marker === selected ? "true" : undefined}
              className={`rounded border bg-white p-3 text-sm ${
                c.marker === selected ? "border-sky-500 ring-1 ring-sky-500" : ""
              }`}
            >
              <p className="font-medium">
                [{c.marker}] {c.title}
              </p>
              <p className="text-slate-600">
                {c.publisher} · {formatDate(c.published_on)}
                {page ? ` · ${page}` : ""}
              </p>
              <blockquote className="mt-2 border-l-2 pl-2 text-slate-700">{c.excerpt}</blockquote>
              {c.canonical_url ? (
                <a
                  href={c.canonical_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 inline-block text-sky-700 underline"
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
