import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import type { Citation } from "../api/types";
import {
  CITATION_STATUS_LABEL,
  CITATION_STATUS_NOTE,
  EXCERPT_REMOVED_NOTE,
  citationStatus,
} from "../lib/citations";
import { formatDate, pageLabel } from "../lib/format";
import { cx } from "../ui/controlClass";
import { IconButton } from "../ui/IconButton";
import { NewTabLink } from "../ui/NewTabLink";

interface Props {
  citations: Citation[];
  selected: number;
  onClose: () => void;
}

// UX-16 (mockup 1): the sources of an answer.
// - From 1024 px a 380 px column beside the thread that scrolls on its own and brings the
//   selected source into view.
// - From 768 px a drawer on the right, over the thread.
// - On phone a bottom sheet (at most 85% of the screen) showing one source at a time,
//   with "1 of 2", previous and next.
// It stays a "Citations" landmark at every width; Escape or Close closes it.
// UX-24: opening a source moves focus to the panel's heading, so a screen reader announces
// the panel and reads on into the sources; closing it returns focus to the marker that
// opened it.
export function CitationPanel({ citations, selected, onClose }: Props) {
  // The source the phone sheet shows: the selected one until previous or next is used.
  const [pick, setPick] = useState({ from: selected, shown: selected });
  const shown = pick.from === selected ? pick.shown : selected;
  const index = Math.max(
    0,
    citations.findIndex((c) => c.marker === shown),
  );
  const list = useRef<HTMLOListElement>(null);
  const panel = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  // "View at source" is described by its source's title, so it is clear out of context.
  const titleId = useId();

  useEffect(() => {
    const active = document.activeElement;
    if (active instanceof HTMLElement && !panel.current?.contains(active)) opener.current = active;
    heading.current?.focus({ preventScroll: true });
  }, [selected]);

  useEffect(() => {
    const inPanel = panel.current;
    return () => {
      const active = document.activeElement;
      const lost = !active || active === document.body || !!inPanel?.contains(active);
      if (lost && opener.current?.isConnected) opener.current.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    list.current?.querySelector(`[data-marker="${shown}"]`)?.scrollIntoView({ block: "nearest" });
  }, [shown]);

  function go(step: number) {
    const next = citations[index + step];
    if (next) setPick({ from: selected, shown: next.marker });
  }

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape") onClose();
  }

  return (
    <aside
      ref={panel}
      aria-label="Citations"
      onKeyDown={onKeyDown}
      className={cx(
        "fixed inset-x-0 bottom-0 z-20 flex max-h-[85dvh] flex-col rounded-t-dialog bg-surface shadow-overlay",
        "md:inset-x-auto md:inset-y-0 md:right-0 md:max-h-none md:w-95 md:rounded-none md:border-l",
        "lg:sticky lg:top-0 lg:h-dvh lg:shrink-0 lg:self-start lg:shadow-none",
      )}
    >
      <div
        aria-hidden="true"
        className="mx-auto mt-2 h-1 w-9 rounded-badge bg-line-strong md:hidden"
      />
      <div className="flex items-center gap-1 border-b py-2 pr-2 pl-4 md:py-3 md:pl-5">
        <h2
          ref={heading}
          tabIndex={-1}
          className="flex-1 text-heading font-strong focus:outline-none"
        >
          Sources{" "}
          <span className="text-meta font-normal text-fg-muted md:hidden">
            {index + 1} of {citations.length}
          </span>
        </h2>
        <div className="flex md:hidden">
          <IconButton
            label="Previous source"
            icon={ChevronLeft}
            disabled={index === 0}
            onClick={() => go(-1)}
          />
          <IconButton
            label="Next source"
            icon={ChevronRight}
            disabled={index >= citations.length - 1}
            onClick={() => go(1)}
          />
        </div>
        <IconButton label="Close" icon={X} onClick={onClose} />
      </div>
      <ol ref={list} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
        {citations.map((c) => {
          const page = pageLabel(c.type, c.page_or_slide);
          const status = citationStatus(c);
          const current = c.marker === selected;
          return (
            <li
              key={c.marker}
              data-marker={c.marker}
              data-testid={`citation-${c.marker}`}
              aria-current={current ? "true" : undefined}
              className={cx(
                "relative flex flex-col gap-2 rounded-card border bg-surface p-3 text-ui",
                current && "border-selected ring-1 ring-selected",
                c.marker !== shown && "max-md:hidden",
                "max-md:border-0 max-md:p-0 max-md:ring-0",
              )}
            >
              <p className="flex items-start gap-2">
                <span
                  aria-hidden="true"
                  className="shrink-0 rounded-control bg-primary px-1.5 text-meta font-strong text-on-primary"
                >
                  {c.marker}
                </span>
                <span id={`${titleId}-${c.marker}`} className="font-emphasis">
                  <span className="sr-only">[{c.marker}] </span>
                  {c.title}
                  {status ? (
                    <span
                      data-testid={`citation-status-${c.marker}`}
                      title={CITATION_STATUS_NOTE[status]}
                      className="ml-2 rounded-badge bg-warning-muted px-1.5 py-0.5 text-meta font-normal text-warning"
                    >
                      {CITATION_STATUS_LABEL[status]}
                    </span>
                  ) : null}
                </span>
              </p>
              {status ? (
                <p className="text-meta text-warning">{CITATION_STATUS_NOTE[status]}</p>
              ) : null}
              <p className="text-meta text-fg-muted">
                {c.publisher} · {formatDate(c.published_on)}
                {page ? ` · ${page}` : ""}
              </p>
              {c.excerpt ? (
                <blockquote className="rounded-control bg-surface-subtle px-3 py-2.5 text-fg-secondary">
                  {c.excerpt}
                </blockquote>
              ) : (
                <p data-testid={`citation-no-excerpt-${c.marker}`} className="text-fg-subtle">
                  {EXCERPT_REMOVED_NOTE}
                </p>
              )}
              {c.canonical_url ? (
                <NewTabLink href={c.canonical_url} aria-describedby={`${titleId}-${c.marker}`}>
                  View at source
                </NewTabLink>
              ) : null}
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
