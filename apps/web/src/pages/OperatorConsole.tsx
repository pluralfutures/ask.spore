import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError, operatorApi } from "../api/client";
import { formatDate } from "../lib/format";
import { errorText } from "../lib/operator";

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
    <main className="mx-auto flex max-w-4xl flex-col gap-6 p-4">
      <h1 className="text-xl font-semibold">Operator console</h1>
      <section className="rounded bg-white p-3 text-sm">
        <h2 className="mb-2 font-semibold">Tenants</h2>
        <ul className="flex flex-col gap-1">
          {tenants.data?.map((tenant) => (
            <li key={tenant.id}>
              <Link to={`/operator/tenants/${tenant.id}`} className="underline">
                {tenant.display_name}
              </Link>{" "}
              <span className="text-slate-500">
                ({tenant.slug}) · {tenant.status} · admins: {tenant.admins}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-2">
          <Link to="/operator/aggregates" className="underline">
            Totals across tenants
          </Link>
        </p>
      </section>
      <CreateTenant />
      <Sources />
      <section>
        <h2 className="mb-2 font-semibold">Notices</h2>
        {notices.data?.length ? (
          <ul className="text-sm">
            {notices.data.map((n) => (
              <li key={n.id}>
                {formatDate(n.created_at)} · {n.tenant_slug} · {n.kind}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-600">No notices.</p>
        )}
      </section>
    </main>
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
  const files = sources.data?.filter((s) => ["pdf", "docx", "pptx"].includes(s.type)) ?? [];
  return (
    <section className="rounded bg-white p-3 text-sm">
      <h2 className="mb-2 font-semibold">Downloadable files</h2>
      {errorText(toggle.error) ? <p className="text-red-700">{errorText(toggle.error)}</p> : null}
      {files.length === 0 ? <p className="text-slate-600">No files in the register.</p> : null}
      <ul className="flex flex-col gap-1">
        {files.map((source) => (
          <li key={source.id}>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={source.downloadable}
                disabled={!source.stored || toggle.isPending}
                onChange={(e) => toggle.mutate({ id: source.id, downloadable: e.target.checked })}
              />
              {source.title} · {source.publisher} · {source.licence_basis} ·{" "}
              {source.tags.join(", ")}
              {source.stored ? null : <span className="text-slate-600">(no stored copy)</span>}
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function OperatorsOnly() {
  return <main className="mx-auto max-w-3xl p-4 text-sm">Operators only.</main>;
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
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2 rounded bg-white p-3 text-sm">
      <h2 className="w-full font-semibold">New tenant</h2>
      <label className="flex flex-col">
        Slug
        <input
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          required
          className="border px-1"
        />
      </label>
      <label className="flex flex-col">
        Display name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          className="border px-1"
        />
      </label>
      <label className="flex flex-col">
        Verified domains (comma-separated)
        <input
          value={domains}
          onChange={(e) => setDomains(e.target.value)}
          className="border px-1"
        />
      </label>
      <button type="submit" className="rounded bg-slate-900 px-3 py-1 text-white">
        Create
      </button>
      {errorText(create.error) && <p className="w-full text-red-700">{errorText(create.error)}</p>}
    </form>
  );
}
