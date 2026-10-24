import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { contentApi } from "../../api/client";
import type { Takedown } from "../../api/types";
import { errorMessage, timerText, timerTone } from "../../lib/content";
import { formatDate } from "../../lib/format";
import { LINK } from "../../ui/link";

// The takedown queue with its SLA timer (P1b-03, P1b-05): 10 working days from the
// request, the same day for a licence breach we find ourselves. Withdrawal is a separate
// reviewer step on the source's page.
export function Takedowns() {
  const queue = useQuery({ queryKey: ["content", "takedowns"], queryFn: contentApi.takedowns });
  if (queue.error) return <p className="text-danger">{errorMessage(queue.error)}</p>;
  return queue.data ? <TakedownTable items={queue.data} /> : <p>Loading…</p>;
}

const TONE = { overdue: "text-danger font-strong", due: "text-attention", ok: "" };

export function TakedownTable({ items }: { items: Takedown[] }) {
  if (items.length === 0) return <p className="text-fg-muted">No open takedown requests.</p>;
  return (
    <table className="w-full rounded-control bg-surface text-left">
      <thead>
        <tr className="border-b">
          <th className="p-2">Source</th>
          <th className="p-2">Reference</th>
          <th className="p-2">Requested</th>
          <th className="p-2">Due</th>
          <th className="p-2">Timer</th>
          <th className="p-2">Status</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.source_id} className="border-b">
            <td className="p-2">
              <Link to={`/content/sources/${item.source_id}`} className={LINK}>
                {item.title}
              </Link>
              {item.licence_grounds ? (
                <span className="ml-1 text-meta">(licence grounds)</span>
              ) : null}
            </td>
            <td className="p-2">{item.reference}</td>
            <td className="p-2">{formatDate(item.requested_on)}</td>
            <td className="p-2">{formatDate(item.due_on)}</td>
            <td
              data-testid={`timer-${item.source_id}`}
              className={`p-2 ${TONE[timerTone(item.working_days_left)]}`}
            >
              {timerText(item.working_days_left)}
            </td>
            <td className="p-2">{item.status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
