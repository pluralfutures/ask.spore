import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState, type FormEvent, type ReactNode } from "react";

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
import { Field } from "../ui/Field";
import { Input, Select, Textarea } from "../ui/Input";
import { Switch } from "../ui/Switch";
import { Notice } from "../ui/Notice";
import { Loading } from "../ui/States";
import { Card } from "../ui/Card";
import { PageHeader } from "../ui/PageHeader";
import { StatusBadge } from "../ui/Badge";
import { ActionsTh, Table, Td, Th } from "../ui/Table";
import { Disclosure } from "../ui/Disclosure";

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
    return (
      <div className="mx-auto w-full max-w-3xl p-4 md:px-8 md:py-6 text-ui">
        Tenant admins only.
      </div>
    );
  }
  return <>{children}</>;
}

// Tenant admin pages (P1a-13): users, workspaces (instructions and defaults), retention.
export function TenantAdmin() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  if (me.isPending)
    return (
      <div className="mx-auto w-full max-w-3xl p-4 md:px-8 md:py-6">
        <Loading />
      </div>
    );
  return (
    <AdminGate me={me.data}>
      <div className="mx-auto w-full flex max-w-4xl flex-col gap-6 p-4 md:px-8 md:py-6">
        <PageHeader back={{ to: "/", label: "← Conversations" }} title="Administration" />
        <Users selfEmail={me.data?.email} />
        <Workspaces />
        <Retention />
        <SignInPolicy />
        <AuditLog />
      </div>
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
    <Card title="Users" className="text-ui">
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
      {failed ? <Notice tone="danger">{failed}</Notice> : null}
      {done && !failed ? (
        <Notice tone="success" role="status">
          {done}
        </Notice>
      ) : null}
      <Table>
        <thead>
          <tr>
            <Th>Name</Th>
            <Th>Email</Th>
            <Th>Role</Th>
            <Th>Status</Th>
            <Th>Last login</Th>
            <ActionsTh />
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
      </Table>
    </Card>
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
      <Td label="Name">{user.display_name}</Td>
      <Td label="Email" className="break-all">
        {user.email}
      </Td>
      <Td label="Role">
        {actions.canChangeRole ? (
          <Select
            aria-label={`Role of ${user.email}`}
            value={user.role}
            onChange={(e) => onChange({ role: e.target.value as "user" | "tenant_admin" })}
          >
            <option value="user">User</option>
            <option value="tenant_admin">Admin</option>
          </Select>
        ) : user.role === "tenant_admin" ? (
          "Admin"
        ) : (
          "User"
        )}
      </Td>
      <Td label="Status">
        <StatusBadge kind="user" status={user.status} />
      </Td>
      <Td label="Last login">{lastLogin(user)}</Td>
      <Td className="text-right">
        <UserActions
          before={[
            ...(actions.canDeactivate
              ? [{ label: "Deactivate", onSelect: () => onChange({ status: "deactivated" }) }]
              : []),
            ...(actions.canReactivate
              ? [{ label: "Reactivate", onSelect: () => onChange({ status: "active" }) }]
              : []),
          ]}
          user={user}
          canResend={actions.canResend}
          canRemove={actions.canRemove}
          onResend={onResend}
          onRemove={onRemove}
          busy={busy}
        />
      </Td>
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
      <Field label="Email">
        <Input value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field label="Name">
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Role">
        <Select value={role} onChange={(e) => setRole(e.target.value as "user" | "tenant_admin")}>
          <option value="user">User</option>
          <option value="tenant_admin">Admin</option>
        </Select>
      </Field>
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
      {refusal(invite.error) ? (
        <Notice tone="danger" className="w-full">
          {refusal(invite.error)}
        </Notice>
      ) : null}
    </form>
  );
}

function Workspaces() {
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: adminApi.settings });
  return (
    <section className="flex flex-col gap-3 text-ui">
      <h2 className="text-heading font-strong">Workspaces</h2>
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
    <Card title={workspace.name} level={3} data-testid={`workspace-${workspace.slug}`}>
      <Defaults workspace={workspace} models={models} modes={modes} />
      <Instructions workspace={workspace} />
    </Card>
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
      <Field label="Default mode">
        <Select value={mode} onChange={(e) => setMode(e.target.value)}>
          {modes.map((m) => (
            <option key={m} value={m}>
              {MODE_LABELS[m] ?? m}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Default model">
        <Select
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
        </Select>
      </Field>
      <Switch
        checked={reasoning}
        disabled={!switchable}
        onChange={(e) => setReasoning(e.target.checked)}
      >
        Reasoning by default
      </Switch>
      <Button variant="primary" type="submit" disabled={save.isPending}>
        Save defaults
      </Button>
      {save.isSuccess ? <span className="text-fg-muted">Saved.</span> : null}
      {refusal(save.error) ? (
        <Notice tone="danger" className="w-full">
          {refusal(save.error)}
        </Notice>
      ) : null}
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
      <Textarea
        id={`instructions-${workspace.id}`}
        value={text}
        onChange={(e) => {
          setDraft(e.target.value);
          setSavedVersion(null);
        }}
        maxLength={MAX_INSTRUCTIONS_CHARS}
        rows={4}
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
      {refusal(save.error) ? <Notice tone="danger">{refusal(save.error)}</Notice> : null}
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
    <Disclosure summary={`Version history (${versions.length})`}>
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
    </Disclosure>
  );
}

// P1b-07: the tenant's sign-in methods and SSO source, as the operator configured them
// with the client's IT. Read-only: changes go through the operator.
function SignInPolicy() {
  const policy = useQuery({ queryKey: ["admin", "login-policy"], queryFn: adminApi.loginPolicy });
  return (
    <Card title="Sign-in" className="text-ui">
      {policy.data ? <PolicySummary policy={policy.data} /> : null}
      <p className="text-fg-muted">To change single sign-on, contact the platform operator.</p>
    </Card>
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
    <Card title="Chat history retention" className="text-ui">
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
      <form onSubmit={submit} noValidate className="mt-2 flex items-start gap-2">
        <Field label="Days" error={error}>
          <Input
            type="number"
            min={0}
            max={MAX_RETENTION_DAYS}
            value={current}
            onChange={(e) => setValue(e.target.value)}
            className="w-20"
          />
        </Field>
        {/* mt-6: level with the input, below the field's label */}
        <Button variant="primary" type="submit" disabled={save.isPending} className="mt-6">
          Save retention
        </Button>
      </form>
      {refusal(save.error) ? <Notice tone="danger">{refusal(save.error)}</Notice> : null}
    </Card>
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
    <Card title="Audit log" className="text-ui">
      <p className="text-fg-muted">
        Sign-in, administration, operator and notice-acceptance events of the last 90 days, as CSV.
      </p>
      <Button
        variant="primary"
        className="w-fit"
        disabled={download.isPending}
        onClick={() => download.mutate()}
      >
        Download audit log
      </Button>
      {refusal(download.error) ? <Notice tone="danger">{refusal(download.error)}</Notice> : null}
    </Card>
  );
}
