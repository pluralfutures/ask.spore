import Markdown from "react-markdown";

import { linkMarkers, markerFromHref } from "../lib/citations";
import { LINK } from "../ui/link";

interface Props {
  text: string;
  markers: ReadonlySet<number>;
  onCite: (marker: number) => void;
}

// Answers are model output: rendered as Markdown without raw HTML (react-markdown's
// default), with valid [n] markers as buttons that open the citation panel.
export function AnswerMarkdown({ text, markers, onCite }: Props) {
  return (
    <div className="prose-sm space-y-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5">
      <Markdown
        components={{
          a: ({ href, children }) => {
            const marker = markerFromHref(href);
            if (marker !== null) {
              return (
                <button
                  type="button"
                  onClick={() => onCite(marker)}
                  aria-label={`Citation ${marker}`}
                  className="mx-0.5 rounded-control bg-cite-bg px-1 text-meta font-emphasis text-cite hover:bg-cite-bg-hover"
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
        }}
      >
        {linkMarkers(text, markers)}
      </Markdown>
    </div>
  );
}
