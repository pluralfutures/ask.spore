import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { contentApi } from "../../api/client";
import type { ContentSite, SiteCreateIn } from "../../api/types";
import {
  ALLOW_DECISIONS,
  SCHEDULES,
  canEdit,
  errorMessage,
  parsePatterns,
} from "../../lib/content";
import { formatDate } from "../../lib/format";
import { Button } from "../../ui/Button";
import { LINK } from "../../ui/link";
import { Field } from "../../ui/Field";
import { Input, Select, Textarea } from "../../ui/Input";
import { Checkbox } from "../../ui/Checkbox";

// Sites (P1b-04, P1b-05): registered websites, their crawl state, and the editor's form
// to register one for a reviewer to approve.
export function Sites({ roles }: { roles: string[] }) {
  const sites = useQuery({ queryKey: ["content", "sites"], queryFn: contentApi.sites });
  return (
    <section className="flex flex-col gap-4">
      {errorMessage(sites.error) ? (
        <p className="text-danger">{errorMessage(sites.error)}</p>
      ) : null}
      {sites.data ? <SiteTable sites={sites.data} /> : <p>Loading…</p>}
      {canEdit(roles) ? <RegisterSite /> : null}
    </section>
  );
}

export function SiteTable({ sites }: { sites: ContentSite[] }) {
  if (sites.length === 0) return <p className="text-fg-muted">No sites registered.</p>;
  return (
    <table className="w-full rounded-control bg-surface text-left">
      <thead>
        <tr className="border-b">
          <th className="p-2">Site</th>
          <th className="p-2">Status</th>
          <th className="p-2">Allow decision</th>
          <th className="p-2">Schedule</th>
          <th className="p-2">Last crawl</th>
          <th className="p-2">Pages</th>
          <th className="p-2">Blocked</th>
        </tr>
      </thead>
      <tbody>
        {sites.map((site) => (
          <tr key={site.id} className="border-b">
            <td className="p-2">
              <Link to={`/content/sites/${site.id}`} className={LINK}>
                {site.name}
              </Link>{" "}
              <span className="text-fg-subtle">{site.host}</span>
            </td>
            <td className="p-2">{site.status}</td>
            <td className="p-2">{ALLOW_DECISIONS[site.allow_decision] ?? site.allow_decision}</td>
            <td className="p-2">{site.schedule}</td>
            <td className="p-2">
              {site.last_crawl_at
                ? `${formatDate(site.last_crawl_at)} · ${site.last_crawl_status}`
                : "never"}
            </td>
            <td className="p-2">{site.page_count}</td>
            <td className="p-2">{site.blocked_count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RegisterSite() {
  const queryClient = useQueryClient();
  const tags = useQuery({ queryKey: ["content", "tags"], queryFn: contentApi.tags });
  const [form, setForm] = useState({
    start_url: "",
    name: "",
    publisher: "",
    licence_basis: "",
    tags: [] as string[],
    allow: "",
    deny: "",
    schedule: "none" as SiteCreateIn["schedule"],
    max_pages: "50",
  });
  const create = useMutation({
    mutationFn: contentApi.createSite,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["content", "sites"] }),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate({
      start_url: form.start_url.trim(),
      name: form.name.trim(),
      publisher: form.publisher.trim(),
      licence_basis: form.licence_basis.trim(),
      tags: form.tags,
      allow_patterns: parsePatterns(form.allow),
      deny_patterns: parsePatterns(form.deny),
      schedule: form.schedule,
      max_pages: Number(form.max_pages),
    });
  }
  const input = (key: "start_url" | "name" | "publisher" | "licence_basis" | "max_pages") => (
    <Input
      value={form[key]}
      onChange={(e) => setForm({ ...form, [key]: e.target.value })}
      required
    />
  );
  return (
    <form
      onSubmit={submit}
      className="flex max-w-2xl flex-col gap-2 rounded-control bg-surface p-3"
    >
      <h2 className="font-strong">Register a site</h2>
      <Field label="Start URL">{input("start_url")}</Field>
      <Field label="Name">{input("name")}</Field>
      <Field label="Publisher">{input("publisher")}</Field>
      <Field label="Licence basis">{input("licence_basis")}</Field>
      <fieldset className="flex flex-wrap gap-3">
        <legend>Tags</legend>
        {tags.data?.map((t) => (
          <Checkbox
            key={t.tag}
            checked={form.tags.includes(t.tag)}
            onChange={(e) =>
              setForm({
                ...form,
                tags: e.target.checked
                  ? [...form.tags, t.tag]
                  : form.tags.filter((x) => x !== t.tag),
              })
            }
          >
            {t.tag}
          </Checkbox>
        ))}
      </fieldset>
      <Field label="Paths to crawl, one per line (e.g. /reports/*; empty: the whole site)">
        <Textarea
          value={form.allow}
          onChange={(e) => setForm({ ...form, allow: e.target.value })}
        />
      </Field>
      <Field label="Paths never to crawl, one per line">
        <Textarea value={form.deny} onChange={(e) => setForm({ ...form, deny: e.target.value })} />
      </Field>
      <Field label="Schedule">
        <Select
          value={form.schedule}
          onChange={(e) =>
            setForm({ ...form, schedule: e.target.value as SiteCreateIn["schedule"] })
          }
        >
          {SCHEDULES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Page budget">{input("max_pages")}</Field>
      <Button variant="primary" className="w-fit" type="submit" disabled={create.isPending}>
        Register
      </Button>
      {errorMessage(create.error) ? (
        <p className="text-danger">{errorMessage(create.error)}</p>
      ) : null}
      {create.data ? <p>Registered: it waits for a reviewer.</p> : null}
    </form>
  );
}
