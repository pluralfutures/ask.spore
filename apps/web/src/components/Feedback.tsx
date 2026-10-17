import { useState } from "react";

import { api } from "../api/client";

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
    <div className="mt-2 flex items-center gap-2 text-sm">
      {(["up", "down"] as const).map((value) => (
        <button
          key={value}
          type="button"
          aria-label={value === "up" ? "Helpful" : "Not helpful"}
          aria-pressed={rating === value}
          onClick={() => void rate(value)}
          className={`rounded border px-2 ${rating === value ? "bg-slate-200" : ""}`}
        >
          {value === "up" ? "👍" : "👎"}
        </button>
      ))}
      {failed ? <span className="text-red-700">Feedback not saved</span> : null}
    </div>
  );
}
