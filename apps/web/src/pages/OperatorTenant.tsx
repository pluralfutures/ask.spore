import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { ApiError, operatorApi } from "../api/client";
import type {
  EntitlementsIn,
  LoginPolicyIn,
  OperatorOptions,
  OperatorTag,
  OperatorWorkspace,
  SsoSourceIn,
  TenantOut,
} from "../api/types";
import { lastLogin } from "../lib/admin";
import { formFrom, toRequest, type EntitlementsForm } from "../lib/entitlements";
import { formatDate } from "../lib/format";
import { TENANT_TABS, errorText, tabFrom, toggle, type TenantTab } from "../lib/operator";
import { capShare, count, euros } from "../lib/spend";
import { emptySourceForm, sourceBody, type SourceForm, type SsoKind } from "../lib/sso";
import { OperatorsOnly } from "./OperatorConsole";
import { PolicySummary } from "./TenantAdmin";

const TAB_LABELS: Record<TenantTab, string> = {
  entitlements: "Entitlements",
  login: "Login policy",
  workspaces: "Workspaces",
  users: "Users",
  spend: "Spend",
};

// One tenant per page (P1b-12, Phase 1a findings F2): every form on this page is keyed
// to the tenant in the URL and is re-created when the tenant changes, so a save can
// only go to the tenant whose name is shown above it. The entitlement save also names
// the tenant in its body, and the API refuses it if that is not the path's tenant.
export function OperatorTenant() {
  const { tenantId = "" } = useParams();
  return <TenantPage key={tenantId} tenantId={tenantId} />;
}

function TenantPage({ tenantId }: { tenantId: string }) {
  const [params, setParams] = useSearchParams();
  const tab = tabFrom(params.get("tab"));
  const tenant = useQuery({
    queryKey: ["operator", "tenant", tenantId],
    queryFn: () => operatorApi.tenant(tenantId),
  });
  const options = useQuery({ queryKey: ["operator", "options"], queryFn: operatorApi.options });

  if (tenant.error instanceof ApiError && tenant.error.status === 403) return <OperatorsOnly />;
  if (tenant.error) return <main className="mx-auto max-w-3xl p-4 text-sm">No such tenant.</main>;
  if (!tenant.data || !options.data) {
    return <main className="mx-auto max-w-3xl p-4 text-sm">Loading…</main>;
  }
  const current = tenant.data;
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-4 p-4 text-sm">
      <p>
        <Link to="/operator" className="underline">
          Operator console
        </Link>
      </p>
      <header>
        <h1 className="text-xl font-semibold">
          {current.display_name} <span className="text-slate-500">({current.slug})</span>
        </h1>
        <p className="text-slate-600">
          {current.status} · admins: {current.admins} · domains:{" "}
          {current.verified_domains.join(", ") || "none"}
        </p>
      </header>
      <nav className="flex gap-3 border-b" aria-label="Tenant settings">
        {TENANT_TABS.map((name) => (
          <button
            key={name}
            type="button"
            aria-current={name === tab ? "page" : undefined}
            onClick={() => setParams({ tab: name })}
            className={name === tab ? "border-b-2 border-slate-900 font-semibold" : ""}
          >
            {TAB_LABELS[name]}
          </button>
        ))}
      </nav>
      {tab === "entitlements" && <Entitlements tenant={current} options={options.data} />}
      {tab === "login" && (
        <>
          <LoginPolicy tenant={current} />
          <SsoSource tenant={current} />
        </>
      )}
      {tab === "workspaces" && <Workspaces tenant={current} />}
      {tab === "users" && <Users tenant={current} />}
      {tab === "spend" && <Spend tenant={current} />}
    </main>
  );
}

function useRefreshTenant(tenantId: string): () => Promise<void> {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ["operator", "tenant", tenantId] });
    await queryClient.invalidateQueries({ queryKey: ["operator", "tenants"] });
  };
}

function Entitlements({ tenant, options }: { tenant: TenantOut; options: OperatorOptions }) {
  const [form, setForm] = useState<EntitlementsForm>(() => formFrom(tenant.entitlements));
  const [problem, setProblem] = useState<string | null>(null);
  const refresh = useRefreshTenant(tenant.id);
  const save = useMutation({
    mutationFn: ({ tenantId, body }: { tenantId: string; body: EntitlementsIn }) =>
      operatorApi.setEntitlements(tenantId, body),
    onSuccess: refresh,
  });
  const ent = tenant.entitlements;

  function submit(event: FormEvent) {
    event.preventDefault();
    const result = toRequest(tenant.id, form, ent);
    if ("error" in result) {
      setProblem(result.error);
      return;
    }
    setProblem(null);
    save.mutate(result);
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 rounded bg-white p-3">
      <fieldset className="flex gap-3">
        <legend>Answer modes</legend>
        {options.answer_modes.map((mode) => (
          <label key={mode}>
            <input
              type="checkbox"
              checked={form.answerModes.includes(mode)}
              disabled={mode === "corpus_only"}
              onChange={(e) =>
                setForm({ ...form, answerModes: toggle(form.answerModes, mode, e.target.checked) })
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
        Save entitlements for {tenant.display_name}
      </button>
      {save.isSuccess && <p>Saved.</p>}
      {(problem ?? errorText(save.error)) && (
        <p className="text-red-700">{problem ?? errorText(save.error)}</p>
      )}
    </form>
  );
}

// P1b-06: how the tenant's users sign in. Sign-in links are on by default; the operator
// switches them off once the client's SSO is live and their IT asks for it.
function LoginPolicy({ tenant }: { tenant: TenantOut }) {
  const current = tenant.login_policy;
  const [form, setForm] = useState<LoginPolicyIn>({
    sign_in_links_enabled: current.sign_in_links_enabled,
    jit_provisioning_enabled: current.jit_provisioning_enabled,
    admin_mfa_required: current.admin_mfa_required,
  });
  const refresh = useRefreshTenant(tenant.id);
  const save = useMutation({
    mutationFn: () => operatorApi.setLoginPolicy(tenant.id, form),
    onSuccess: refresh,
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
      className="flex flex-wrap items-center gap-3 rounded bg-white p-3"
    >
      <h2 className="w-full font-semibold">Login policy</h2>
      {box("sign_in_links_enabled", "Sign-in links")}
      {box("jit_provisioning_enabled", "Create users on first SSO sign-in (verified domains)")}
      {box("admin_mfa_required", "Second factor for tenant admins")}
      <button type="submit" className="rounded bg-slate-900 px-3 py-1 text-white">
        Save login policy
      </button>
      {errorText(save.error) && <p className="w-full text-red-700">{errorText(save.error)}</p>}
    </form>
  );
}

// P1b-07: the tenant's one SSO source, configured in Authentik with the client's IT. The
// client secret is sent once and never shown again; leave it empty to keep it.
function SsoSource({ tenant }: { tenant: TenantOut }) {
  const current = tenant.login_policy;
  const [form, setForm] = useState<SourceForm>(() =>
    emptySourceForm(current.sso_source_kind === "none" ? "entra" : current.sso_source_kind),
  );
  const [problem, setProblem] = useState<string | null>(null);
  const refresh = useRefreshTenant(tenant.id);
  const save = useMutation({
    mutationFn: (body: SsoSourceIn) => operatorApi.setSsoSource(tenant.id, body),
    onSuccess: () => {
      setForm({ ...form, clientSecret: "" });
      void refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () => operatorApi.removeSsoSource(tenant.id),
    onSuccess: refresh,
  });
  const field = (key: keyof SourceForm, label: string, type = "text") => (
    <label className="flex flex-col">
      {label}
      <input
        type={type}
        autoComplete="off"
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        className="border px-1"
      />
    </label>
  );

  function submit(event: FormEvent) {
    event.preventDefault();
    const result = sourceBody(form);
    if ("error" in result) {
      setProblem(result.error);
      return;
    }
    setProblem(null);
    save.mutate(result.body);
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 rounded bg-white p-3">
      <h2 className="font-semibold">Single sign-on source</h2>
      <PolicySummary policy={current} />
      <label className="flex gap-2">
        Kind
        <select
          value={form.kind}
          onChange={(e) => setForm({ ...form, kind: e.target.value as SsoKind })}
          className="border"
        >
          <option value="entra">Microsoft Entra ID</option>
          <option value="google">Google Workspace</option>
          <option value="oidc">OpenID Connect</option>
          <option value="saml">SAML 2.0</option>
        </select>
      </label>
      <div className="flex flex-wrap items-end gap-2">
        {form.kind === "entra" && field("entraTenantId", "Entra tenant ID")}
        {form.kind === "oidc" && field("issuer", "Issuer (https)")}
        {form.kind !== "saml" && field("clientId", "Client ID")}
        {form.kind !== "saml" && field("clientSecret", "Client secret", "password")}
        {form.kind === "entra" &&
          field("adminGroupIds", "Admin group object IDs (comma-separated, optional)")}
      </div>
      {form.kind === "saml" && (
        <label className="flex flex-col">
          IdP metadata (XML)
          <textarea
            value={form.metadataXml}
            onChange={(e) => setForm({ ...form, metadataXml: e.target.value })}
            rows={4}
            className="border px-1 font-mono text-xs"
          />
        </label>
      )}
      <div className="flex gap-2">
        <button type="submit" className="rounded bg-slate-900 px-3 py-1 text-white">
          Save SSO source
        </button>
        {current.sso_source_kind !== "none" && (
          <button type="button" onClick={() => remove.mutate()} className="underline">
            Remove SSO source
          </button>
        )}
      </div>
      {(problem ?? errorText(save.error) ?? errorText(remove.error)) && (
        <p className="text-red-700">
          {problem ?? errorText(save.error) ?? errorText(remove.error)}
        </p>
      )}
    </form>
  );
}

// Package builder (P1a-04): the tenant's workspaces and their tags. The pickers offer
// only this tenant's own tags and the shared ones (P1b-12); the API refuses any other.
function Workspaces({ tenant }: { tenant: TenantOut }) {
  const queryClient = useQueryClient();
  const key = ["operator", "workspaces", tenant.id];
  const workspaces = useQuery({ queryKey: key, queryFn: () => operatorApi.workspaces(tenant.id) });
  const tags = useQuery({
    queryKey: ["operator", "tags", tenant.id],
    queryFn: () => operatorApi.tenantTags(tenant.id),
  });
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
    <div className="flex flex-col gap-2 rounded bg-white p-3">
      {workspaces.data?.map((workspace) => (
        <WorkspaceTags
          key={workspace.id}
          tenantId={tenant.id}
          workspace={workspace}
          tags={tags.data ?? []}
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
  tags: OperatorTag[];
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
      {tags.map(({ tag, shared }) => (
        <label key={tag}>
          <input
            type="checkbox"
            checked={selected.includes(tag)}
            onChange={(e) => setSelected(toggle(selected, tag, e.target.checked))}
          />{" "}
          {tag}
          {shared ? <span className="text-slate-500"> (shared)</span> : null}
        </label>
      ))}
      <button type="submit" className="rounded bg-slate-900 px-3 py-1 text-white">
        Save tags
      </button>
      {errorText(save.error) && <p className="w-full text-red-700">{errorText(save.error)}</p>}
    </form>
  );
}

function Users({ tenant }: { tenant: TenantOut }) {
  const queryClient = useQueryClient();
  const key = ["operator", "users", tenant.id];
  const users = useQuery({ queryKey: key, queryFn: () => operatorApi.tenantUsers(tenant.id) });
  const refresh = useRefreshTenant(tenant.id);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const invite = useMutation({
    mutationFn: () =>
      operatorApi.inviteAdmin(tenant.id, { email: email.trim(), display_name: name.trim() }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: key });
      await refresh();
    },
  });

  return (
    <div className="flex flex-col gap-3 rounded bg-white p-3">
      <table className="text-left">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Role</th>
            <th>Status</th>
            <th>Last sign-in</th>
          </tr>
        </thead>
        <tbody>
          {users.data?.map((user) => (
            <tr key={user.id}>
              <td>{user.display_name}</td>
              <td>{user.email}</td>
              <td>{user.role}</td>
              <td>{user.status}</td>
              <td>{lastLogin(user)}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
            value={email}
            onChange={(e) => setEmail(e.target.value)}
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
          Invite
        </button>
        {invite.isSuccess && (
          <p className="w-full">
            Invited. An invitation email is on its way; they sign in from their own browser.
          </p>
        )}
        {errorText(invite.error) && (
          <p className="w-full text-red-700">{errorText(invite.error)}</p>
        )}
      </form>
    </div>
  );
}

// P1b-12: month-to-date usage by model from the usage ledger, and external spend against
// the cap with the two notice thresholds (80 percent: notice; 100 percent: hard stop).
function Spend({ tenant }: { tenant: TenantOut }) {
  const spend = useQuery({
    queryKey: ["operator", "spend", tenant.id],
    queryFn: () => operatorApi.tenantSpend(tenant.id),
  });
  if (!spend.data) return <p>{errorText(spend.error) ?? "Loading…"}</p>;
  const data = spend.data;
  const share = capShare(data.external_spent_cents, data.external_spend_cap_cents ?? null);
  return (
    <div className="flex flex-col gap-3 rounded bg-white p-3">
      <h2 className="font-semibold">Month to date ({data.month}, UTC)</h2>
      <p>
        External models: {data.external_models_enabled ? "enabled" : "off"} · spent{" "}
        {euros(data.external_spent_cents)}
        {data.external_spend_cap_cents === null || data.external_spend_cap_cents === undefined
          ? " · no cap"
          : ` of ${euros(data.external_spend_cap_cents)} (${share}%)`}
      </p>
      {data.thresholds.length > 0 && (
        <ul>
          {data.thresholds.map((t) => (
            <li key={t.percent}>
              {t.percent}% at {euros(t.cents)}: {t.reached ? "reached" : "not reached"}
              {t.notified_at ? `, operators notified ${formatDate(t.notified_at)}` : ""}
            </li>
          ))}
        </ul>
      )}
      {data.models.length === 0 ? (
        <p className="text-slate-600">No usage this month.</p>
      ) : (
        <table className="text-left">
          <thead>
            <tr>
              <th>Model</th>
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
                  {m.external ? <span className="text-slate-500"> (outside the EU)</span> : null}
                </td>
                <td>{count(m.tokens_in)}</td>
                <td>{count(m.tokens_out)}</td>
                <td>{euros(m.cost_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
