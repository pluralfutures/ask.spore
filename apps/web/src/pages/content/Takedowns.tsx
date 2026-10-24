import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { contentApi } from "../../api/client";
import type { Takedown } from "../../api/types";
import { errorMessage, timerText, timerTone } from "../../lib/content";
import { formatDate } from "../../lib/format";
import { LINK } from "../../ui/link";
import { Notice } from "../../ui/Notice";
import { Loading } from "../../ui/States";
import { StatusBadge } from "../../ui/Badge";
import { EmptyState } from "../../ui/States";
import { Table, Td, Th } from "../../ui/Table";

// The takedown queue with its SLA timer (P1b-03, P1b-05): 10 working days from the
// request, the same day for a licence breach we find ourselves. Withdrawal is a separate
// reviewer step on the source's page.
export function Takedowns() {
  const queue = useQuery({ queryKey: ["content", "takedowns"], queryFn: contentApi.takedowns });
  if (queue.error) return <Notice tone="danger">{errorMessage(queue.error)}</Notice>;
  return queue.data ? <TakedownTable items={queue.data} /> : <Loading />;
}

const TONE = { overdue: "text-danger font-strong", due: "text-attention", ok: "" };

export function TakedownTable({ items }: { items: Takedown[] }) {
  if (items.length === 0) return <EmptyState title="No open takedown requests." />;
  return (
    <Table>
      <thead>
        <tr>
          <Th>Source</Th>
          <Th>Reference</Th>
          <Th>Requested</Th>
          <Th>Due</Th>
          <Th>Timer</Th>
          <Th>Status</Th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.source_id}>
            <Td label="Source">
              <Link to={`/content/sources/${item.source_id}`} className={LINK}>
                {item.title}
              </Link>
              {item.licence_grounds ? (
                <span className="ml-1 text-meta">(licence grounds)</span>
              ) : null}
            </Td>
            <Td label="Reference">{item.reference}</Td>
            <Td label="Requested">{formatDate(item.requested_on)}</Td>
            <Td label="Due">{formatDate(item.due_on)}</Td>
            <Td
              label="Timer"
              data-testid={`timer-${item.source_id}`}
              className={TONE[timerTone(item.working_days_left)]}
            >
              {timerText(item.working_days_left)}
            </Td>
            <Td label="Status">
              <StatusBadge kind="takedown" status={item.status} />
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
