import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import {
  countLine,
  publishersLine,
  SUMMARY_EMPTY,
  SUMMARY_HEADING,
  updatedLine,
  yearsLine,
} from "../lib/workspaceSummary";
import { cardClass } from "../ui/cardClass";
import { LINK } from "../ui/link";

// P2B-05: what the selected workspace holds, under the home page's question box. Plain
// text and one link. While it loads, or if it cannot be loaded, nothing is shown: the home
// page never reports an error for it.
export function WorkspaceSummaryCard({ workspaceId }: { workspaceId: string }) {
  const summary = useQuery({
    queryKey: ["workspace-summary", workspaceId],
    queryFn: () => api.workspaceSummary(workspaceId),
  });
  if (!summary.data) return null;
  const data = summary.data;
  const lines =
    data.document_count > 0
      ? [countLine(data), publishersLine(data), yearsLine(data), updatedLine(data)]
      : [];
  return (
    <section
      aria-labelledby="summary-title"
      data-testid="workspace-summary"
      className={cardClass("flex flex-col gap-2 p-4")}
    >
      <h2 id="summary-title" className="text-heading font-strong">
        {SUMMARY_HEADING}
      </h2>
      {data.document_count === 0 ? (
        <p className="text-ui text-fg-secondary">{SUMMARY_EMPTY}</p>
      ) : (
        <>
          <ul role="list" className="flex flex-col gap-0.5 text-ui text-fg-secondary">
            {lines.map((line) => (line ? <li key={line}>{line}</li> : null))}
          </ul>
          <Link
            to={`/w/${workspaceId}/files`}
            aria-label="See all files in this workspace"
            className={`w-fit text-ui ${LINK}`}
          >
            See all files
          </Link>
        </>
      )}
    </section>
  );
}
