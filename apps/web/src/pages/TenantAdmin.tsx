import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { ApiError, adminApi, api } from "../api/client";
import type { AdminUser, LoginPolicyOut, Me, ModelOption, Workspace } from "../api/types";
import {
  MAX_INSTRUCTIONS_CHARS,
  MAX_RETENTION_DAYS,
  adminRefusal,
  isTenantAdmin,
  lastLogin,
  parseRetention,
  userActions,
} from "../lib/admin";
import { formatDate } from "../lib/format";
import { policySummary } from "../lib/sso";
import { modelLabel } from "../lib/startPanel";

function refusal(error: unknown): string | null {
  if (error === null || error === undefined) return null;
  return adminRefusal(error instanceof ApiError ? error.code : null);
}

const MODE_LABELS: Record<string, string> = {
  corpus_only: "Sources only",
  general_knowledge: "General knowledge",
};

// Only tenant admins see the pages; the API refuses everyone else anyway (403).
export function AdminGate({ me, children }: { me: Me | null | undefined; children: ReactNode }) {
  if (!isTenantAdmin(me)) {
    return <main className="mx-auto max-w-3xl p-4 text-sm">Tenant admins only.</main>;
  }
  return <>{children}</>;
}

// Tenant admin pages (P1a-13): users, workspaces (instructions and defaults), retention.
export function TenantAdmin() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  if (me.isPending) return <main className="mx-auto max-w-3xl p-4">Loading…</main>;
  return (
    <AdminGate me={me.data}>
      <main className="mx-auto flex max-w-4xl flex-col gap-6 p-4">
        <Link to="/" className="text-sm underline">
          ← Conversations
        </Link>
        <h1 className="text-xl font-semibold">Administration</h1>
        <Users selfEmail={me.data?.email} />
        <Workspaces />
        <Retention />
        <SignInPolicy />
        <AuditLog />
      </main>
    </AdminGate>
  );
}

function Users({ selfEmail }: { selfEmail: string | undefined }) {
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: adminApi.users });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
  const change = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof adminApi.changeUser>[1] }) =>
      adminApi.changeUser(id, body),
    onSuccess: refresh,
  });

  return (
    <section className="flex flex-col gap-2 rounded bg-white p-3 text-sm">
      <h2 className="font-semibold">Users</h2>
      <Invite onInvited={refresh} />
      {refusal(change.error) ? <p className="text-red-700">{refusal(change.error)}</p> : null}
      <table className="w-full text-left">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Role</th>
            <th>Status</th>
            <th>Last login</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.data?.map((user) => (
            <UserRow
              key={user.id}
              user={user}
              selfEmail={selfEmail}
              onChange={(body) => change.mutate({ id: user.id, body })}
            />
          ))}
        </tbody>
      </table>
    </section>
  );
}

function UserRow({
  user,
  selfEmail,
  onChange,
}: {
  user: AdminUser;
  selfEmail: string | undefined;
  onChange: (body: { role?: "user" | "tenant_admin"; status?: "active" | "deactivated" }) => void;
}) {
  const actions = userActions(user, selfEmail);
  return (
    <tr data-testid={`user-${user.email}`}>
      <td>{user.display_name}</td>
      <td>{user.email}</td>
      <td>
        {actions.canChangeRole ? (
          <select
            aria-label={`Role of ${user.email}`}
            value={user.role}
            onChange={(e) => onChange({ role: e.target.value as "user" | "tenant_admin" })}
          >
            <option value="user">User</option>
            <option value="tenant_admin">Admin</option>
          </select>
        ) : user.role === "tenant_admin" ? (
          "Admin"
        ) : (
          "User"
        )}
      </td>
      <td>{user.status}</td>
      <td>{lastLogin(user)}</td>
      <td>
        {actions.canDeactivate ? (
          <button
            type="button"
            className="underline"
            onClick={() => onChange({ status: "deactivated" })}
          >
            Deactivate
          </button>
        ) : null}
        {actions.canReactivate ? (
          <button
            type="button"
            className="underline"
            onClick={() => onChange({ status: "active" })}
          >
            Reactivate
          </button>
        ) : null}
      </td>
    </tr>
  );
}

function Invite({ onInvited }: { onInvited: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"user" | "tenant_admin">("user");
  const invite = useMutation({
    mutationFn: adminApi.invite,
    onSuccess: () => {
      setEmail("");
      setName("");
      onInvited();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    invite.mutate({ email: email.trim(), display_name: name.trim(), role });
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col">
        Email
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded border px-2"
        />
      </label>
      <label className="flex flex-col">
        Name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="rounded border px-2"
        />
      </label>
      <label className="flex flex-col">
        Role
        <select value={role} onChange={(e) => setRole(e.target.value as "user" | "tenant_admin")}>
          <option value="user">User</option>
          <option value="tenant_admin">Admin</option>
        </select>
      </label>
      <button
        type="submit"
        disabled={invite.isPending || !email.trim() || !name.trim()}
        className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50"
      >
        Invite
      </button>
      {invite.isSuccess ? (
        <p className="w-full text-slate-600">
          Invited. They sign in by requesting a link on the sign-in page.
        </p>
      ) : null}
      {refusal(invite.error) ? (
        <p className="w-full text-red-700">{refusal(invite.error)}</p>
      ) : null}
    </form>
  );
}

function Workspaces() {
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: adminApi.settings });
  return (
    <section className="flex flex-col gap-3 text-sm">
      <h2 className="font-semibold">Workspaces</h2>
      {workspaces.data && models.data && settings.data
        ? workspaces.data.map((w) => (
            <WorkspacePanel
              key={w.id}
              workspace={w}
              models={models.data}
              modes={settings.data.answer_modes}
            />
          ))
        : null}
    </section>
  );
}

function WorkspacePanel({
  workspace,
  models,
  modes,
}: {
  workspace: Workspace;
  models: ModelOption[];
  modes: string[];
}) {
  return (
    <div
      className="flex flex-col gap-3 rounded bg-white p-3"
      data-testid={`workspace-${workspace.slug}`}
    >
      <h3 className="font-semibold">{workspace.name}</h3>
      <Defaults workspace={workspace} models={models} modes={modes} />
      <Instructions workspace={workspace} />
    </div>
  );
}

function Defaults({
  workspace,
  models,
  modes,
}: {
  workspace: Workspace;
  models: ModelOption[];
  modes: string[];
}) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState(workspace.default_mode);
  const [model, setModel] = useState(workspace.default_model);
  const [reasoning, setReasoning] = useState(workspace.default_reasoning);
  const save = useMutation({
    mutationFn: () =>
      adminApi.setDefaults(workspace.id, {
        default_mode: mode as "corpus_only" | "general_knowledge",
        default_model: model,
        default_reasoning: reasoning,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workspaces"] }),
  });
  const switchable = models.find((m) => m.id === model)?.reasoning_switch ?? false;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
      className="flex flex-wrap items-end gap-2"
    >
      <label className="flex flex-col">
        Default mode
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          {modes.map((m) => (
            <option key={m} value={m}>
              {MODE_LABELS[m] ?? m}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col">
        Default model
        <select
          value={model}
          onChange={(e) => {
            setModel(e.target.value);
            if (!models.find((m) => m.id === e.target.value)?.reasoning_switch) setReasoning(false);
          }}
        >
          {models.some((m) => m.id === model) ? null : <option value={model}>{model}</option>}
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {modelLabel(m)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1">
        <input
          type="checkbox"
          checked={reasoning}
          disabled={!switchable}
          onChange={(e) => setReasoning(e.target.checked)}
        />
        Reasoning by default
      </label>
      <button
        type="submit"
        disabled={save.isPending}
        className="rounded bg-slate-900 px-3 py-1 text-white"
      >
        Save defaults
      </button>
      {save.isSuccess ? <span className="text-slate-600">Saved.</span> : null}
      {refusal(save.error) ? <p className="w-full text-red-700">{refusal(save.error)}</p> : null}
    </form>
  );
}

function Instructions({ workspace }: { workspace: Workspace }) {
  const queryClient = useQueryClient();
  const key = ["admin", "prompts", workspace.id];
  const history = useQuery({ queryKey: key, queryFn: () => adminApi.prompts(workspace.id) });
  const [draft, setDraft] = useState<string | null>(null);
  const text = draft ?? history.data?.[0]?.text ?? "";
  const save = useMutation({
    mutationFn: (saved: string) => adminApi.savePrompt(workspace.id, saved),
    // The draft stays until the reloaded history holds the saved version (so the field
    // never shows the previous one in between), and is cleared only if it is still the
    // text that was saved: an edit typed while the save ran is kept (P1b-13 f).
    onSuccess: async (_, saved) => {
      await queryClient.invalidateQueries({ queryKey: key });
      setDraft((current) => (current === saved ? null : current));
    },
  });

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={`instructions-${workspace.id}`} className="font-medium">
        Additional instructions
      </label>
      <p className="text-slate-600">
        Added to the assistant&apos;s instructions for this workspace. They cannot change how it
        cites sources or when it declines to answer.
      </p>
      <textarea
        id={`instructions-${workspace.id}`}
        value={text}
        onChange={(e) => setDraft(e.target.value)}
        maxLength={MAX_INSTRUCTIONS_CHARS}
        rows={4}
        className="rounded border px-2 py-1"
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => save.mutate(text)}
          disabled={save.isPending || draft === null}
          className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50"
        >
          Save as new version
        </button>
        <span className="text-slate-600">
          {text.length} / {MAX_INSTRUCTIONS_CHARS}
        </span>
      </div>
      {refusal(save.error) ? <p className="text-red-700">{refusal(save.error)}</p> : null}
      <VersionHistory versions={history.data ?? []} />
    </div>
  );
}

// Every saved version, newest first. Read-only: there is no revert in Phase 1a.
export function VersionHistory({
  versions,
}: {
  versions: { version: number; text: string; created_at: string }[];
}) {
  if (versions.length === 0) return <p className="text-slate-600">No versions saved yet.</p>;
  return (
    <details>
      <summary>Version history ({versions.length})</summary>
      <ol className="flex flex-col gap-2">
        {versions.map((v) => (
          <li key={v.version} data-testid={`version-${v.version}`}>
            <p className="font-medium">
              Version {v.version} · {formatDate(v.created_at)}
            </p>
            <pre className="whitespace-pre-wrap text-slate-700">{v.text || "(empty)"}</pre>
          </li>
        ))}
      </ol>
    </details>
  );
}

// P1b-07: the tenant's sign-in methods and SSO source, as the operator configured them
// with the client's IT. Read-only: changes go through the operator.
function SignInPolicy() {
  const policy = useQuery({ queryKey: ["admin", "login-policy"], queryFn: adminApi.loginPolicy });
  return (
    <section className="flex flex-col gap-2 rounded bg-white p-3 text-sm">
      <h2 className="font-semibold">Sign-in</h2>
      {policy.data ? <PolicySummary policy={policy.data} /> : null}
      <p className="text-slate-600">To change single sign-on, contact the platform operator.</p>
    </section>
  );
}

export function PolicySummary({ policy }: { policy: LoginPolicyOut }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3">
      {policySummary(policy).map(([label, value]) => (
        <Fragment key={label}>
          <dt className="text-slate-600">{label}</dt>
          <dd className="break-all">{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

function Retention() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: adminApi.settings });
  const [value, setValue] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: adminApi.setRetention,
    onSuccess: (saved) => {
      queryClient.setQueryData(["admin", "settings"], saved);
      setValue(null);
    },
  });
  const current = value ?? String(settings.data?.retention_days ?? MAX_RETENTION_DAYS);

  function submit(event: FormEvent) {
    event.preventDefault();
    const parsed = parseRetention(current);
    if ("error" in parsed) {
      setError(parsed.error);
      return;
    }
    setError(null);
    save.mutate(parsed.days);
  }

  return (
    <section className="rounded bg-white p-3 text-sm">
      <h2 className="font-semibold">Chat history retention</h2>
      <p className="text-slate-600">
        Conversations are deleted after this many days, at most {MAX_RETENTION_DAYS}. Shortening it
        also removes existing conversations older than the new limit.
      </p>
      <form onSubmit={submit} noValidate className="mt-2 flex items-end gap-2">
        <label className="flex flex-col">
          Days
          <input
            type="number"
            min={1}
            max={MAX_RETENTION_DAYS}
            value={current}
            onChange={(e) => setValue(e.target.value)}
            className="w-20 rounded border px-2"
          />
        </label>
        <button
          type="submit"
          disabled={save.isPending}
          className="rounded bg-slate-900 px-3 py-1 text-white"
        >
          Save retention
        </button>
      </form>
      {error ? <p className="text-red-700">{error}</p> : null}
      {refusal(save.error) ? <p className="text-red-700">{refusal(save.error)}</p> : null}
    </section>
  );
}

// P1b-10 (architecture §7.2): the tenant's sign-in, admin, operator and consent events.
function AuditLog() {
  const download = useMutation({
    mutationFn: adminApi.auditLog,
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "audit-log.csv";
      link.click();
      URL.revokeObjectURL(url);
    },
  });
  return (
    <section className="rounded bg-white p-3 text-sm">
      <h2 className="font-semibold">Audit log</h2>
      <p className="text-slate-600">
        Sign-in, administration, operator and notice-acceptance events of the last 90 days, as CSV.
      </p>
      <button
        type="button"
        disabled={download.isPending}
        onClick={() => download.mutate()}
        className="mt-2 rounded bg-slate-900 px-3 py-1 text-white"
      >
        Download audit log
      </button>
      {refusal(download.error) ? <p className="text-red-700">{refusal(download.error)}</p> : null}
    </section>
  );
}
