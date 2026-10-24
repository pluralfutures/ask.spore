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
  retentionSummary,
  userActions,
} from "../lib/admin";
import { UserActions } from "../components/UserActions";
import { formatDate } from "../lib/format";
import { policySummary } from "../lib/sso";
import { modelLabel } from "../lib/startPanel";
import { Button } from "../ui/Button";
import { LINK } from "../ui/link";

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
    return <main className="mx-auto max-w-3xl p-4 text-ui">Tenant admins only.</main>;
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
        <Link to="/" className={`text-ui ${LINK}`}>
          ← Conversations
        </Link>
        <h1 className="text-title font-strong">Administration</h1>
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
  // P1c-07: resend an invitation; remove a user.
  const [done, setDone] = useState<string | null>(null);
  const [inviteForm, setInviteForm] = useState(0);
  const resend = useMutation({
    mutationFn: (user: AdminUser) => adminApi.resendInvitation(user.id),
    onSuccess: (_, user) => setDone(`Invitation sent again to ${user.email}.`),
  });
  const remove = useMutation({
    mutationFn: (user: AdminUser) => adminApi.removeUser(user.id),
    onSuccess: async (_, user) => {
      setDone(`${user.email} was removed with their conversations.`);
      await refresh();
    },
  });
  const failed = refusal(change.error) ?? refusal(resend.error) ?? refusal(remove.error);

  return (
    <section className="flex flex-col gap-2 rounded-control bg-surface p-3 text-ui">
      <h2 className="font-strong">Users</h2>
      {/* Release F4: each action shows its own outcome only. An invite clears the list's
          last status; a resend or removal remounts the form, clearing its last refusal. */}
      <Invite
        key={inviteForm}
        onInvited={refresh}
        onStart={() => {
          setDone(null);
          resend.reset();
          remove.reset();
          change.reset();
        }}
      />
      {failed ? <p className="text-danger">{failed}</p> : null}
      {done && !failed ? (
        <p role="status" className="text-fg-secondary">
          {done}
        </p>
      ) : null}
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
              onResend={() => {
                setDone(null);
                setInviteForm((n) => n + 1);
                remove.reset();
                resend.mutate(user);
              }}
              onRemove={() => {
                setDone(null);
                setInviteForm((n) => n + 1);
                resend.reset();
                remove.mutate(user);
              }}
              busy={resend.isPending || remove.isPending}
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
  onResend,
  onRemove,
  busy,
}: {
  user: AdminUser;
  selfEmail: string | undefined;
  onChange: (body: { role?: "user" | "tenant_admin"; status?: "active" | "deactivated" }) => void;
  onResend: () => void;
  onRemove: () => void;
  busy: boolean;
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
          <Button variant="ghost" size="sm" onClick={() => onChange({ status: "deactivated" })}>
            Deactivate
          </Button>
        ) : null}
        {actions.canReactivate ? (
          <Button variant="ghost" size="sm" onClick={() => onChange({ status: "active" })}>
            Reactivate
          </Button>
        ) : null}
        <UserActions
          user={user}
          canResend={actions.canResend}
          canRemove={actions.canRemove}
          onResend={onResend}
          onRemove={onRemove}
          busy={busy}
        />
      </td>
    </tr>
  );
}

function Invite({ onInvited, onStart }: { onInvited: () => void; onStart: () => void }) {
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
    onStart();
    invite.mutate({ email: email.trim(), display_name: name.trim(), role });
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col">
        Email
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-control border px-2"
        />
      </label>
      <label className="flex flex-col">
        Name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="rounded-control border px-2"
        />
      </label>
      <label className="flex flex-col">
        Role
        <select value={role} onChange={(e) => setRole(e.target.value as "user" | "tenant_admin")}>
          <option value="user">User</option>
          <option value="tenant_admin">Admin</option>
        </select>
      </label>
      <Button
        variant="primary"
        type="submit"
        disabled={invite.isPending || !email.trim() || !name.trim()}
      >
        Invite
      </Button>
      {invite.isSuccess ? (
        <p className="w-full text-fg-muted">
          Invited. They sign in by requesting a link on the sign-in page.
        </p>
      ) : null}
      {refusal(invite.error) ? <p className="w-full text-danger">{refusal(invite.error)}</p> : null}
    </form>
  );
}

function Workspaces() {
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: adminApi.settings });
  return (
    <section className="flex flex-col gap-3 text-ui">
      <h2 className="font-strong">Workspaces</h2>
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
      className="flex flex-col gap-3 rounded-control bg-surface p-3"
      data-testid={`workspace-${workspace.slug}`}
    >
      <h3 className="font-strong">{workspace.name}</h3>
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
      <Button variant="primary" type="submit" disabled={save.isPending}>
        Save defaults
      </Button>
      {save.isSuccess ? <span className="text-fg-muted">Saved.</span> : null}
      {refusal(save.error) ? <p className="w-full text-danger">{refusal(save.error)}</p> : null}
    </form>
  );
}

function Instructions({ workspace }: { workspace: Workspace }) {
  const queryClient = useQueryClient();
  const key = ["admin", "prompts", workspace.id];
  const history = useQuery({ queryKey: key, queryFn: () => adminApi.prompts(workspace.id) });
  const [draft, setDraft] = useState<string | null>(null);
  // P1c-11: the version the last save created, shown once the save has fully landed
  // (history reloaded, draft settled); the end of a save is visible, not inferred.
  const [savedVersion, setSavedVersion] = useState<number | null>(null);
  const text = draft ?? history.data?.[0]?.text ?? "";
  const save = useMutation({
    mutationFn: (saved: string) => adminApi.savePrompt(workspace.id, saved),
    // The draft stays until the reloaded history holds the saved version (so the field
    // never shows the previous one in between), and is cleared only if it is still the
    // text that was saved: an edit typed while the save ran is kept (P1b-13 f).
    onSuccess: async (result, saved) => {
      await queryClient.invalidateQueries({ queryKey: key });
      setDraft((current) => (current === saved ? null : current));
      setSavedVersion(result.version);
    },
  });

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={`instructions-${workspace.id}`} className="font-emphasis">
        Additional instructions
      </label>
      <p className="text-fg-muted">
        Added to the assistant&apos;s instructions for this workspace. They cannot change how it
        cites sources or when it declines to answer.
      </p>
      <textarea
        id={`instructions-${workspace.id}`}
        value={text}
        onChange={(e) => {
          setDraft(e.target.value);
          setSavedVersion(null);
        }}
        maxLength={MAX_INSTRUCTIONS_CHARS}
        rows={4}
        className="rounded-control border px-2 py-1"
      />
      <div className="flex items-center gap-2">
        <Button
          variant="primary"
          onClick={() => save.mutate(text)}
          disabled={save.isPending || draft === null}
        >
          Save as new version
        </Button>
        <span className="text-fg-muted">
          {text.length} / {MAX_INSTRUCTIONS_CHARS}
        </span>
        {savedVersion !== null && !save.isPending ? (
          <span role="status" className="text-fg-muted">
            Saved as version {savedVersion}.
          </span>
        ) : null}
      </div>
      {refusal(save.error) ? <p className="text-danger">{refusal(save.error)}</p> : null}
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
  if (versions.length === 0) return <p className="text-fg-muted">No versions saved yet.</p>;
  return (
    <details>
      <summary>Version history ({versions.length})</summary>
      <ol className="flex flex-col gap-2">
        {versions.map((v) => (
          <li key={v.version} data-testid={`version-${v.version}`}>
            <p className="font-emphasis">
              Version {v.version} · {formatDate(v.created_at)}
            </p>
            <pre className="whitespace-pre-wrap text-fg-secondary">{v.text || "(empty)"}</pre>
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
    <section className="flex flex-col gap-2 rounded-control bg-surface p-3 text-ui">
      <h2 className="font-strong">Sign-in</h2>
      {policy.data ? <PolicySummary policy={policy.data} /> : null}
      <p className="text-fg-muted">To change single sign-on, contact the platform operator.</p>
    </section>
  );
}

export function PolicySummary({ policy }: { policy: LoginPolicyOut }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3">
      {policySummary(policy).map(([label, value]) => (
        <Fragment key={label}>
          <dt className="text-fg-muted">{label}</dt>
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
    <section className="rounded-control bg-surface p-3 text-ui">
      <h2 className="font-strong">Chat history retention</h2>
      <p className="text-fg-muted">
        Conversations are deleted after this many days, at most {MAX_RETENTION_DAYS}. Shortening it
        also removes existing conversations older than the new limit. 0 keeps no history: each
        conversation is deleted as soon as its answer ends.
      </p>
      {settings.data ? (
        <p className="text-fg-muted" data-testid="retention-summary">
          {retentionSummary(settings.data.retention_days)}
        </p>
      ) : null}
      <form onSubmit={submit} noValidate className="mt-2 flex items-end gap-2">
        <label className="flex flex-col">
          Days
          <input
            type="number"
            min={0}
            max={MAX_RETENTION_DAYS}
            value={current}
            onChange={(e) => setValue(e.target.value)}
            className="w-20 rounded-control border px-2"
          />
        </label>
        <Button variant="primary" type="submit" disabled={save.isPending}>
          Save retention
        </Button>
      </form>
      {error ? <p className="text-danger">{error}</p> : null}
      {refusal(save.error) ? <p className="text-danger">{refusal(save.error)}</p> : null}
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
    <section className="rounded-control bg-surface p-3 text-ui">
      <h2 className="font-strong">Audit log</h2>
      <p className="text-fg-muted">
        Sign-in, administration, operator and notice-acceptance events of the last 90 days, as CSV.
      </p>
      <Button
        variant="primary"
        className="mt-2"
        disabled={download.isPending}
        onClick={() => download.mutate()}
      >
        Download audit log
      </Button>
      {refusal(download.error) ? <p className="text-danger">{refusal(download.error)}</p> : null}
    </section>
  );
}
