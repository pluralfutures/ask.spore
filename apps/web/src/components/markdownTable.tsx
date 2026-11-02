import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// P2B-01: GitHub-flavoured Markdown (tables, strikethrough, task lists, footnotes) for the
// two places that render Markdown: model answers and the consent notice. Raw HTML stays off
// (react-markdown's default); the plugin adds no HTML pass-through.
export const GFM_PLUGINS = [remarkGfm];

// A wide table scrolls sideways inside its own region, so the page never scrolls
// horizontally at phone width. The region is focusable so a keyboard user can scroll it.
export const TABLE_COMPONENTS: Pick<Components, "table" | "th" | "td"> = {
  table: ({ children }) => (
    <div
      role="group"
      aria-label="Table"
      tabIndex={0}
      className="max-w-full overflow-x-auto rounded-control focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <table className="w-full border-collapse text-ui">{children}</table>
    </div>
  ),
  th: ({ children, style }) => (
    <th
      scope="col"
      style={style}
      className="border border-line bg-surface-subtle px-3 py-1.5 text-left align-top font-emphasis"
    >
      {children}
    </th>
  ),
  td: ({ children, style }) => (
    <td style={style} className="border border-line px-3 py-1.5 text-left align-top">
      {children}
    </td>
  ),
};
