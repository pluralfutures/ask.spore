import type { ReactNode } from "react";

import type { Citation } from "../api/types";
import { AnswerMarkdown } from "./AnswerMarkdown";
import { Feedback } from "./Feedback";
import { Badge } from "../ui/Badge";

interface Props {
  text: string;
  citations: Citation[];
  unsupported: boolean;
  abstained: boolean;
  messageId: string | null; // null while streaming
  onCite: (marker: number) => void;
  // UX-15: the answer-quality notes (partial, truncated, failover) sit inside the block,
  // under the text they qualify, above the feedback footer.
  notes?: ReactNode;
}

export function AssistantMessage(props: Props) {
  const { text, citations, unsupported, abstained, messageId, onCite, notes } = props;
  if (abstained) {
    return (
      <div
        data-testid="nothing-found"
        className="rounded-card border border-dashed bg-surface p-4 text-fg-muted"
      >
        <p className="font-emphasis">Nothing relevant found</p>
        <p className="text-ui">{text}</p>
        {notes}
        {messageId ? <AnswerFooter messageId={messageId} /> : null}
      </div>
    );
  }
  const markers = new Set(citations.map((c) => c.marker));
  return (
    <article className="flex flex-col gap-3 rounded-card border bg-surface p-4 md:px-6 md:py-5">
      {unsupported ? (
        <Badge tone="danger" data-testid="unsupported" className="w-fit">
          Unsupported answer: no citations to your sources
        </Badge>
      ) : null}
      <AnswerMarkdown text={text} markers={markers} onCite={onCite} />
      {notes}
      {messageId ? <AnswerFooter messageId={messageId} /> : null}
    </article>
  );
}

function AnswerFooter({ messageId }: { messageId: string }) {
  return (
    <footer className="mt-1 border-t pt-3">
      <Feedback messageId={messageId} />
    </footer>
  );
}
