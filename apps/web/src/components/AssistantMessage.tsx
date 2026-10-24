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
}

export function AssistantMessage(props: Props) {
  const { text, citations, unsupported, abstained, messageId, onCite } = props;
  if (abstained) {
    return (
      <div
        data-testid="nothing-found"
        className="rounded-card border border-dashed bg-surface p-4 text-fg-muted"
      >
        <p className="font-emphasis">Nothing relevant found</p>
        <p className="text-ui">{text}</p>
        {messageId ? <Feedback messageId={messageId} /> : null}
      </div>
    );
  }
  const markers = new Set(citations.map((c) => c.marker));
  return (
    <div className="rounded-card border bg-surface p-4">
      {unsupported ? (
        <Badge tone="danger" data-testid="unsupported" className="mb-2">
          Unsupported answer: no citations to your sources
        </Badge>
      ) : null}
      <AnswerMarkdown text={text} markers={markers} onCite={onCite} />
      {messageId ? <Feedback messageId={messageId} /> : null}
    </div>
  );
}
