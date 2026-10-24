import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { ApiError, operatorApi } from "../api/client";
import { errorText } from "../lib/operator";
import { count, euros } from "../lib/spend";
import { OperatorsOnly } from "./OperatorConsole";
import { LINK } from "../ui/link";

// Cross-tenant totals for the month (P1b-12, architecture §7.4): tokens and cost per
// model and per provider, and how many tenants used each. No tenant is named here and
// no query text exists to show; a tenant's own figures are on its page.
export function OperatorAggregates() {
  const totals = useQuery({
    queryKey: ["operator", "aggregates"],
    queryFn: operatorApi.aggregates,
  });
  if (totals.error instanceof ApiError && totals.error.status === 403) return <OperatorsOnly />;
  const data = totals.data;
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-4 p-4 text-ui">
      <p>
        <Link to="/operator" className={LINK}>
          Operator console
        </Link>
      </p>
      <h1 className="text-title font-strong">Totals across tenants</h1>
      {!data ? (
        <p>{errorText(totals.error) ?? "Loading…"}</p>
      ) : (
        <>
          <p>
            {data.month} (UTC) · {data.tenants_with_usage} of {data.tenants} tenants used a model
            this month.
          </p>
          <table className="rounded-control bg-surface text-left">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Tokens in</th>
                <th>Tokens out</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.providers.map((p) => (
                <tr key={p.provider}>
                  <td>{p.provider}</td>
                  <td>{count(p.tokens_in)}</td>
                  <td>{count(p.tokens_out)}</td>
                  <td>{euros(p.cost_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table className="rounded-control bg-surface text-left">
            <thead>
              <tr>
                <th>Model</th>
                <th>Tenants</th>
                <th>Tokens in</th>
                <th>Tokens out</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.models.map((m) => (
                <tr key={m.model}>
                  <td>
                    {m.display_name}
                    {m.external ? <span className="text-fg-subtle"> (outside the EU)</span> : null}
                  </td>
                  <td>{m.tenants}</td>
                  <td>{count(m.tokens_in)}</td>
                  <td>{count(m.tokens_out)}</td>
                  <td>{euros(m.cost_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
