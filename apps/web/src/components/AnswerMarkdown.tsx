import { useLayoutEffect, useMemo, useRef } from "react";
import Markdown, { type Components } from "react-markdown";

import { linkMarkers, markerFromHref } from "../lib/citations";
import { LINK } from "../ui/link";
import { GFM_PLUGINS, TABLE_COMPONENTS } from "./markdownTable";

interface Props {
  text: string;
  markers: ReadonlySet<number>;
  onCite: (marker: number) => void;
}

// Answers are model output: rendered as Markdown without raw HTML (react-markdown's
// default) and GFM tables (P2B-01), with valid [n] markers as buttons that open the citation panel.
export function AnswerMarkdown({ text, markers, onCite }: Props) {
  // UX-16: one components object per answer, so a re-render (opening the citation panel)
  // keeps the same marker buttons and the focus stays on the one activated.
  const cite = useRef(onCite);
  useLayoutEffect(() => {
    cite.current = onCite;
  });
  const components = useMemo<Components>(
    () => ({
      ...TABLE_COMPONENTS,
      h1: ({ children }) => <h2>{children}</h2>,
      a: ({ href, children }) => {
        const marker = markerFromHref(href);
        if (marker !== null) {
          return (
            <button
              type="button"
              onClick={() => cite.current(marker)}
              aria-label={`Citation ${marker}`}
              className="mx-0.5 inline-flex min-h-6 min-w-6 items-center justify-center rounded-control bg-cite-bg px-1.5 align-baseline text-meta font-emphasis text-cite hover:bg-cite-bg-hover"
            >
              {marker}
            </button>
          );
        }
        return (
          <a href={href} target="_blank" rel="noopener noreferrer" className={LINK}>
            {children}
          </a>
        );
      },
    }),
    [],
  );
  return (
    // UX-15: reading type (16/26) with the answer's own structure: headings (the model's
    // # renders as h2, under the conversation title), lists with markers, spaced items.
    <div className="flex flex-col gap-3 text-reading [&_h2,&_h3]:mt-2 [&_h2,&_h3]:text-heading [&_h2,&_h3]:font-strong [&_h4,&_h5,&_h6]:font-strong [&_li]:mt-1.5 [&_ol]:list-decimal [&_ol]:pl-6 [&_ul]:list-disc [&_ul]:pl-6 [&>:first-child]:mt-0">
      <Markdown remarkPlugins={GFM_PLUGINS} components={components}>
        {linkMarkers(text, markers)}
      </Markdown>
    </div>
  );
}
