import { useQuery } from "@tanstack/react-query";

import { ApiError, operatorApi } from "../api/client";
import { errorText } from "../lib/operator";
import { count, euros } from "../lib/spend";
import { OperatorsOnly } from "./OperatorConsole";
import { Notice } from "../ui/Notice";
import { Loading } from "../ui/States";
import { PageHeader } from "../ui/PageHeader";
import { Table, Td, Th } from "../ui/Table";

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
    <div className="mx-auto w-full flex max-w-4xl flex-col gap-4 p-4 md:px-8 md:py-6 text-ui">
      <PageHeader
        back={{ to: "/operator", label: "Operator console" }}
        title="Totals across tenants"
      />
      {!data ? (
        errorText(totals.error) ? (
          <Notice tone="danger">{errorText(totals.error)}</Notice>
        ) : (
          <Loading />
        )
      ) : (
        <>
          <p>
            {data.month} (UTC) · {data.tenants_with_usage} of {data.tenants} tenants used a model
            this month.
          </p>
          <Table>
            <thead>
              <tr>
                <Th>Provider</Th>
                <Th numeric>Tokens in</Th>
                <Th numeric>Tokens out</Th>
                <Th numeric>Cost</Th>
              </tr>
            </thead>
            <tbody>
              {data.providers.map((p) => (
                <tr key={p.provider}>
                  <Td label="Provider">{p.provider}</Td>
                  <Td label="Tokens in" numeric>
                    {count(p.tokens_in)}
                  </Td>
                  <Td label="Tokens out" numeric>
                    {count(p.tokens_out)}
                  </Td>
                  <Td label="Cost" numeric>
                    {euros(p.cost_cents)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Table>
            <thead>
              <tr>
                <Th>Model</Th>
                <Th numeric>Tenants</Th>
                <Th numeric>Tokens in</Th>
                <Th numeric>Tokens out</Th>
                <Th numeric>Cost</Th>
              </tr>
            </thead>
            <tbody>
              {data.models.map((m) => (
                <tr key={m.model}>
                  <Td label="Model">
                    {m.display_name}
                    {m.external ? <span className="text-fg-subtle"> (outside the EU)</span> : null}
                  </Td>
                  <Td label="Tenants" numeric>
                    {m.tenants}
                  </Td>
                  <Td label="Tokens in" numeric>
                    {count(m.tokens_in)}
                  </Td>
                  <Td label="Tokens out" numeric>
                    {count(m.tokens_out)}
                  </Td>
                  <Td label="Cost" numeric>
                    {euros(m.cost_cents)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </>
      )}
    </div>
  );
}
