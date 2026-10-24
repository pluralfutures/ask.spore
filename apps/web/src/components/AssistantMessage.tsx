import type { Citation } from "../api/types";
import { AnswerMarkdown } from "./AnswerMarkdown";
import { Feedback } from "./Feedback";

interface Props {
  text: string;
  citations: Citation[];
  unsupported: boolean;
  abstained: boolean;
  messageId: string | null; // null while streaming
  onCite: (marker: number) => void;
}

export function AssistantMessage(props: Props) {
  const { text, citations, unsupported, abstained, messageId, onCite } = props;
  if (abstained) {
    return (
      <div
        data-testid="nothing-found"
        className="rounded-control border border-dashed p-3 text-fg-muted"
      >
        <p className="font-emphasis">Nothing relevant found</p>
        <p className="text-ui">{text}</p>
        {messageId ? <Feedback messageId={messageId} /> : null}
      </div>
    );
  }
  const markers = new Set(citations.map((c) => c.marker));
  return (
    <div className="rounded-control border bg-surface p-3">
      {unsupported ? (
        <p
          data-testid="unsupported"
          className="mb-2 inline-block rounded-control bg-danger-subtle px-2 text-meta font-emphasis text-danger-strong"
        >
          Unsupported answer: no citations to your sources
        </p>
      ) : null}
      <AnswerMarkdown text={text} markers={markers} onCite={onCite} />
      {messageId ? <Feedback messageId={messageId} /> : null}
    </div>
  );
}
