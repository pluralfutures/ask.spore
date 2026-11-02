import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError, operatorApi } from "../api/client";
import { SaveStatus } from "../components/SaveStatus";
import { formatDate } from "../lib/format";
import { Button } from "../ui/Button";
import { LINK } from "../ui/link";
import { Field } from "../ui/Field";
import { Input } from "../ui/Input";
import { Checkbox } from "../ui/Checkbox";
import { Card } from "../ui/Card";
import { cardClass } from "../ui/cardClass";
import { PageHeader } from "../ui/PageHeader";
import { StatusBadge } from "../ui/Badge";
import { Table, Td, Th } from "../ui/Table";
import { AccessDenied, EmptyState } from "../ui/States";

// Operator console (P1a-03), one tenant per page (P1b-12): this page picks the tenant and
// creates new ones; each tenant's settings are on its own page (OperatorTenant), so a
// save can only ever be made on the tenant it is shown for (Phase 1a findings F2). The
// platform-wide parts stay here: notices, the download switch per source, and a link
// to the cross-tenant totals. The API decides who is an operator; anyone else gets 403.
export function OperatorConsole() {
  const tenants = useQuery({ queryKey: ["operator", "tenants"], queryFn: operatorApi.tenants });
  const notices = useQuery({ queryKey: ["operator", "notices"], queryFn: operatorApi.notices });

  if (tenants.error instanceof ApiError && tenants.error.status === 403) {
    return <OperatorsOnly />;
  }
  return (
    <div className="mx-auto w-full flex max-w-4xl flex-col gap-6 p-4 md:px-8 md:py-6">
      <PageHeader
        title="Operator console"
        actions={
          // P1c-08: every operator is also a user of the internal tenant.
          <Link to="/" className={`text-ui ${LINK}`}>
            Chat app
          </Link>
        }
      />
      {/* UX-19: tenants, downloadable files and notices are tables. */}
      <Card
        title="Tenants"
        className="text-ui"
        actions={
          <Link to="/operator/aggregates" className={LINK}>
            Totals across tenants
          </Link>
        }
      >
        <Table>
          <thead>
            <tr>
              <Th>Tenant</Th>
              <Th>Slug</Th>
              <Th>Status</Th>
              <Th numeric>Admins</Th>
            </tr>
          </thead>
          <tbody>
            {tenants.data?.map((tenant) => (
              <tr key={tenant.id}>
                <Td label="Tenant">
                  <Link to={`/operator/tenants/${tenant.id}`} className={LINK}>
                    {tenant.display_name}
                  </Link>
                </Td>
                <Td label="Slug" className="font-mono text-meta">
                  {tenant.slug}
                </Td>
                <Td label="Status">
                  <StatusBadge kind="tenant" status={tenant.status} />
                </Td>
                <Td label="Admins" numeric>
                  {tenant.admins}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <TerminatedTenants />
      <CreateTenant />
      <Sources />
      <Card title="Notices" className="text-ui">
        {notices.data?.length ? (
          <Table>
            <thead>
              <tr>
                <Th>Date</Th>
                <Th>Tenant</Th>
                <Th>Kind</Th>
              </tr>
            </thead>
            <tbody>
              {notices.data.map((n) => (
                <tr key={n.id}>
                  <Td label="Date">{formatDate(n.created_at)}</Td>
                  <Td label="Tenant" className="font-mono text-meta">
                    {n.tenant_slug}
                  </Td>
                  <Td label="Kind">{n.kind}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <EmptyState title="No notices." />
        )}
      </Card>
    </div>
  );
}

// P1a-14: the licence gate per source. Set from the licence basis: our own analyses, and
// third-party files only where the licence permits redistribution. Audited.
function Sources() {
  const queryClient = useQueryClient();
  const sources = useQuery({ queryKey: ["operator", "sources"], queryFn: operatorApi.sources });
  const toggle = useMutation({
    mutationFn: ({ id, downloadable }: { id: string; downloadable: boolean }) =>
      operatorApi.setDownloadable(id, downloadable),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["operator", "sources"] }),
  });
  // P2B-06: an uploaded Markdown or text file has a stored copy, a crawled page does not.
  const files =
    sources.data?.filter((s) => ["pdf", "docx", "pptx"].includes(s.type) || s.stored) ?? [];
  return (
    <Card title="Downloadable files" className="text-ui">
      <SaveStatus isSuccess={toggle.isSuccess} error={toggle.error} />
      {files.length === 0 ? (
        <EmptyState title="No files in the register." />
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Downloadable</Th>
              <Th>Title</Th>
              <Th>Publisher</Th>
              <Th>Licence basis</Th>
              <Th>Tags</Th>
            </tr>
          </thead>
          <tbody>
            {files.map((source) => (
              <tr key={source.id} data-testid={`source-${source.id}`}>
                <Td label="Downloadable">
                  <Checkbox
                    checked={source.downloadable}
                    disabled={!source.stored || toggle.isPending}
                    onChange={(e) =>
                      toggle.mutate({ id: source.id, downloadable: e.target.checked })
                    }
                  >
                    <span className="sr-only">{source.title}</span>
                  </Checkbox>
                </Td>
                <Td label="Title">
                  <span className="font-emphasis">{source.title}</span>
                  {source.stored ? null : <span className="text-fg-muted"> (no stored copy)</span>}
                </Td>
                <Td label="Publisher">{source.publisher}</Td>
                <Td label="Licence basis">{source.licence_basis}</Td>
                <Td label="Tags">{source.tags.join(", ")}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

// P1c-08 (Phase 1b F5): tenants the termination purge emptied, with the purge's date and
// certificate number; they have no settings page any more.
function TerminatedTenants() {
  const terminated = useQuery({
    queryKey: ["operator", "terminated"],
    queryFn: operatorApi.terminatedTenants,
  });
  if (!terminated.data?.length) return null;
  return (
    <Card title="Terminated tenants" className="text-ui">
      <ul className="flex flex-col gap-1">
        {terminated.data.map((t) => (
          <li key={t.id} data-testid={`terminated-${t.slug}`}>
            {t.display_name} <span className="text-fg-subtle">({t.slug})</span> · {t.status} ·
            purged {t.purged_at ? formatDate(t.purged_at) : "date not recorded"} · certificate{" "}
            {t.certificate ?? "not recorded"}
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function OperatorsOnly() {
  return <AccessDenied>Operators only.</AccessDenied>;
}

function CreateTenant() {
  const queryClient = useQueryClient();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [domains, setDomains] = useState("");
  const create = useMutation({
    mutationFn: operatorApi.createTenant,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["operator", "tenants"] }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate({
      slug: slug.trim(),
      display_name: name.trim(),
      verified_domains: domains
        .split(",")
        .map((d) => d.trim())
        .filter(Boolean),
    });
  }

  return (
    <form onSubmit={submit} className={cardClass("flex flex-wrap items-end gap-2 text-ui")}>
      <h2 className="w-full font-strong">New tenant</h2>
      <Field label="Slug">
        <Input value={slug} onChange={(e) => setSlug(e.target.value)} required />
      </Field>
      <Field label="Display name">
        <Input value={name} onChange={(e) => setName(e.target.value)} required />
      </Field>
      <Field label="Verified domains (comma-separated)">
        <Input value={domains} onChange={(e) => setDomains(e.target.value)} />
      </Field>
      <Button variant="primary" type="submit">
        Create
      </Button>
      <SaveStatus isSuccess={create.isSuccess} error={create.error} savedText="Tenant created." />
    </form>
  );
}
