import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ApiError, operatorApi } from "../api/client";
import type { LoginPolicyIn, OperatorOptions, OperatorWorkspace, TenantOut } from "../api/types";
import { formatDate } from "../lib/format";
import { formFrom, toRequest, type EntitlementsForm } from "../lib/entitlements";

// Operator console, minimum (P1a-03): tenants, first admin, entitlements, notices; and the
// package builder (P1a-04): each tenant's workspaces and the tags that form their corpus.
// The API decides who is an operator; anyone else gets 403 and this page says so.
export function OperatorConsole() {
  const tenants = useQuery({ queryKey: ["operator", "tenants"], queryFn: operatorApi.tenants });
  const options = useQuery({ queryKey: ["operator", "options"], queryFn: operatorApi.options });
  const notices = useQuery({ queryKey: ["operator", "notices"], queryFn: operatorApi.notices });

  if (tenants.error instanceof ApiError && tenants.error.status === 403) {
    return <main className="mx-auto max-w-3xl p-4 text-sm">Operators only.</main>;
  }
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-6 p-4">
      <h1 className="text-xl font-semibold">Operator console</h1>
      <CreateTenant />
      {tenants.data?.map((tenant) =>
        options.data ? (
          <TenantPanel key={tenant.id} tenant={tenant} options={options.data} />
        ) : null,
      )}
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

function errorText(error: unknown): string | null {
  if (error === null || error === undefined) return null;
  return error instanceof ApiError ? `Refused (${error.status}).` : "Something went wrong.";
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

function toggle(list: string[], value: string, on: boolean): string[] {
  return on ? [...new Set([...list, value])] : list.filter((v) => v !== value);
}

function TenantPanel({ tenant, options }: { tenant: TenantOut; options: OperatorOptions }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<EntitlementsForm>(() => formFrom(tenant.entitlements));
  const [problem, setProblem] = useState<string | null>(null);
  const [adminEmail, setAdminEmail] = useState("");
  const [adminName, setAdminName] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["operator", "tenants"] });
  const save = useMutation({
    mutationFn: (body: Parameters<typeof operatorApi.setEntitlements>[1]) =>
      operatorApi.setEntitlements(tenant.id, body),
    onSuccess: refresh,
  });
  const invite = useMutation({
    mutationFn: () =>
      operatorApi.inviteAdmin(tenant.id, {
        email: adminEmail.trim(),
        display_name: adminName.trim(),
      }),
    onSuccess: refresh,
  });
  const ent = tenant.entitlements;

  function submit(event: FormEvent) {
    event.preventDefault();
    const result = toRequest(form, ent);
    if ("error" in result) {
      setProblem(result.error);
      return;
    }
    setProblem(null);
    save.mutate(result.body);
  }

  return (
    <section className="flex flex-col gap-3 rounded bg-white p-3 text-sm">
      <h2 className="font-semibold">
        {tenant.display_name} <span className="text-slate-500">({tenant.slug})</span>
      </h2>
      <p className="text-slate-600">
        {tenant.status} · admins: {tenant.admins} · domains:{" "}
        {tenant.verified_domains.join(", ") || "none"}
      </p>
      <form onSubmit={submit} className="flex flex-col gap-2">
        <fieldset className="flex gap-3">
          <legend>Answer modes</legend>
          {options.answer_modes.map((mode) => (
            <label key={mode}>
              <input
                type="checkbox"
                checked={form.answerModes.includes(mode)}
                disabled={mode === "corpus_only"}
                onChange={(e) =>
                  setForm({
                    ...form,
                    answerModes: toggle(form.answerModes, mode, e.target.checked),
                  })
                }
              />{" "}
              {mode}
            </label>
          ))}
        </fieldset>
        <fieldset className="flex gap-3">
          <legend>Enabled models</legend>
          {options.models.map((model) => (
            <label key={model}>
              <input
                type="checkbox"
                checked={form.enabledModels.includes(model)}
                onChange={(e) =>
                  setForm({
                    ...form,
                    enabledModels: toggle(form.enabledModels, model, e.target.checked),
                  })
                }
              />{" "}
              {model}
            </label>
          ))}
        </fieldset>
        <fieldset className="flex flex-wrap items-end gap-2">
          <legend>External models (served outside the EU)</legend>
          <label>
            <input
              type="checkbox"
              checked={form.externalModelsEnabled}
              onChange={(e) => setForm({ ...form, externalModelsEnabled: e.target.checked })}
            />{" "}
            Enabled
          </label>
          <label className="flex flex-col">
            Monthly spend cap (EUR)
            <input
              inputMode="decimal"
              value={form.spendCapEuros}
              onChange={(e) => setForm({ ...form, spendCapEuros: e.target.value })}
              className="border px-1"
            />
          </label>
          <label className="flex flex-col">
            Client acceptance: DPA document
            <input
              value={form.acceptanceReference}
              onChange={(e) => setForm({ ...form, acceptanceReference: e.target.value })}
              className="border px-1"
            />
          </label>
          <label className="flex flex-col">
            Accepted on
            <input
              type="date"
              value={form.acceptanceDate}
              onChange={(e) => setForm({ ...form, acceptanceDate: e.target.value })}
              className="border px-1"
            />
          </label>
          {ent.external_acceptance_reference && (
            <p className="w-full text-slate-600">
              On file: {ent.external_acceptance_reference}, {ent.external_acceptance_date}
            </p>
          )}
        </fieldset>
        <button type="submit" className="self-start rounded bg-slate-900 px-3 py-1 text-white">
          Save entitlements
        </button>
        {(problem ?? errorText(save.error)) && (
          <p className="text-red-700">{problem ?? errorText(save.error)}</p>
        )}
      </form>
      <LoginPolicy tenant={tenant} />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          invite.mutate();
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <label className="flex flex-col">
          Invite admin: email
          <input
            type="email"
            value={adminEmail}
            onChange={(e) => setAdminEmail(e.target.value)}
            required
            className="border px-1"
          />
        </label>
        <label className="flex flex-col">
          Name
          <input
            value={adminName}
            onChange={(e) => setAdminName(e.target.value)}
            required
            className="border px-1"
          />
        </label>
        <button type="submit" className="rounded bg-slate-900 px-3 py-1 text-white">
          Invite
        </button>
        {invite.isSuccess && (
          <p className="w-full">Invited. They sign in with a link from their own browser.</p>
        )}
        {errorText(invite.error) && (
          <p className="w-full text-red-700">{errorText(invite.error)}</p>
        )}
      </form>
      <Workspaces tenant={tenant} options={options} />
    </section>
  );
}

// P1b-06: how the tenant's users sign in. Sign-in links are on by default; the operator
// switches them off once the client's SSO is live and their IT asks for it.
function LoginPolicy({ tenant }: { tenant: TenantOut }) {
  const queryClient = useQueryClient();
  const current = tenant.login_policy;
  const [form, setForm] = useState<LoginPolicyIn>({
    sign_in_links_enabled: current.sign_in_links_enabled,
    jit_provisioning_enabled: current.jit_provisioning_enabled,
    admin_mfa_required: current.admin_mfa_required,
  });
  const save = useMutation({
    mutationFn: () => operatorApi.setLoginPolicy(tenant.id, form),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["operator", "tenants"] }),
  });
  const box = (key: keyof LoginPolicyIn, label: string) => (
    <label>
      <input
        type="checkbox"
        checked={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.checked })}
      />{" "}
      {label}
    </label>
  );
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
      className="flex flex-wrap items-center gap-3"
    >
      <h3 className="w-full font-semibold">Login policy</h3>
      {box("sign_in_links_enabled", "Sign-in links")}
      {box("jit_provisioning_enabled", "Create users on first SSO sign-in (verified domains)")}
      {box("admin_mfa_required", "Second factor for tenant admins")}
      <span className="text-slate-600">SSO: {current.sso_source_kind}</span>
      <button type="submit" className="rounded bg-slate-900 px-3 py-1 text-white">
        Save login policy
      </button>
      {errorText(save.error) && <p className="w-full text-red-700">{errorText(save.error)}</p>}
    </form>
  );
}

function Workspaces({ tenant, options }: { tenant: TenantOut; options: OperatorOptions }) {
  const queryClient = useQueryClient();
  const key = ["operator", "workspaces", tenant.id];
  const workspaces = useQuery({ queryKey: key, queryFn: () => operatorApi.workspaces(tenant.id) });
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () =>
      operatorApi.createWorkspace(tenant.id, {
        slug: slug.trim(),
        name: name.trim(),
        tag_ids: [],
        default_mode: "corpus_only",
        default_model: tenant.entitlements.enabled_models[0] ?? "",
        default_reasoning: false,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  });

  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-semibold">Workspaces</h3>
      {workspaces.data?.map((workspace) => (
        <WorkspaceTags
          key={workspace.id}
          tenantId={tenant.id}
          workspace={workspace}
          tags={options.tags}
        />
      ))}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <label className="flex flex-col">
          New workspace: slug
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            required
            className="border px-1"
          />
        </label>
        <label className="flex flex-col">
          Name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="border px-1"
          />
        </label>
        <button type="submit" className="rounded bg-slate-900 px-3 py-1 text-white">
          Add workspace
        </button>
        {errorText(create.error) && (
          <p className="w-full text-red-700">{errorText(create.error)}</p>
        )}
      </form>
    </div>
  );
}

function WorkspaceTags({
  tenantId,
  workspace,
  tags,
}: {
  tenantId: string;
  workspace: OperatorWorkspace;
  tags: string[];
}) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string[]>(workspace.tag_ids);
  const save = useMutation({
    mutationFn: () => operatorApi.setWorkspaceTags(tenantId, workspace.id, selected),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["operator", "workspaces", tenantId] }),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
      className="flex flex-wrap items-center gap-3"
    >
      <span>
        {workspace.name} <span className="text-slate-500">({workspace.slug})</span>
      </span>
      {tags.map((tag) => (
        <label key={tag}>
          <input
            type="checkbox"
            checked={selected.includes(tag)}
            onChange={(e) => setSelected(toggle(selected, tag, e.target.checked))}
          />{" "}
          {tag}
        </label>
      ))}
      <button type="submit" className="rounded bg-slate-900 px-3 py-1 text-white">
        Save tags
      </button>
      {errorText(save.error) && <p className="w-full text-red-700">{errorText(save.error)}</p>}
    </form>
  );
}
