import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import { Button } from "../ui/Button";

type Rating = "up" | "down";

export function Feedback({ messageId }: { messageId: string }) {
  const [rating, setRating] = useState<Rating | null>(null);
  const [failed, setFailed] = useState(false);

  async function rate(value: Rating) {
    setFailed(false);
    try {
      await api.sendFeedback(messageId, { rating: value });
      setRating(value);
    } catch {
      setFailed(true);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-ui">
      {(["up", "down"] as const).map((value) => (
        // UX-06: outline thumbs with the names as visible text; on phone the name is
        // visually hidden and stays the accessible name.
        <Button
          key={value}
          size="sm"
          icon={value === "up" ? ThumbsUp : ThumbsDown}
          aria-pressed={rating === value}
          onClick={() => void rate(value)}
        >
          <span className="max-sm:sr-only">{value === "up" ? "Helpful" : "Not helpful"}</span>
        </Button>
      ))}
      {failed ? <span className="text-danger">Feedback not saved</span> : null}
    </div>
  );
}
