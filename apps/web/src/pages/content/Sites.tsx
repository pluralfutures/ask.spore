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
import { EmptyState, Skeleton } from "../../ui/States";
import { LINK } from "../../ui/link";
import { Field } from "../../ui/Field";
import { Input, Select, Textarea } from "../../ui/Input";
import { Checkbox } from "../../ui/Checkbox";
import { Notice } from "../../ui/Notice";
import { cardClass } from "../../ui/cardClass";
import { Globe } from "lucide-react";
import { Badge, StatusBadge } from "../../ui/Badge";
import { UploadCrawl } from "./Uploads";
import { Table, Td, Th } from "../../ui/Table";

// Sites (P1b-04, P1b-05): registered websites, their crawl state, and the editor's form
// to register one for a reviewer to approve. P2SR01-05: upload sites carry an "uploaded"
// badge and their crawl date, and an editor may upload a crawl for a new site.
export function Sites({ roles }: { roles: string[] }) {
  const sites = useQuery({ queryKey: ["content", "sites"], queryFn: contentApi.sites });
  return (
    <section className="flex flex-col gap-4">
      {errorMessage(sites.error) ? (
        <Notice tone="danger">{errorMessage(sites.error)}</Notice>
      ) : null}
      {sites.data ? <SiteTable sites={sites.data} /> : <Skeleton />}
      {canEdit(roles) ? <RegisterSite /> : null}
      {canEdit(roles) ? <UploadCrawl /> : null}
    </section>
  );
}

export function SiteTable({ sites }: { sites: ContentSite[] }) {
  if (sites.length === 0) return <EmptyState title="No sites registered." icon={Globe} />;
  return (
    <Table>
      <thead>
        <tr>
          <Th>Site</Th>
          <Th>Status</Th>
          <Th>Allow decision</Th>
          <Th>Schedule</Th>
          <Th>Last crawl</Th>
          <Th numeric>Pages</Th>
          <Th numeric>Blocked</Th>
        </tr>
      </thead>
      <tbody>
        {sites.map((site) => (
          <tr key={site.id}>
            <Td label="Site">
              <Link to={`/content/sites/${site.id}`} className={LINK}>
                {site.name}
              </Link>{" "}
              <span className="text-fg-subtle">{site.host}</span>
              {site.origin === "upload" ? (
                <>
                  {" "}
                  <Badge data-testid="site-uploaded">uploaded</Badge>
                </>
              ) : null}
            </Td>
            <Td label="Status">
              <StatusBadge kind="site" status={site.status} />
            </Td>
            <Td label="Allow decision">
              {ALLOW_DECISIONS[site.allow_decision] ?? site.allow_decision}
            </Td>
            <Td label="Schedule">{site.origin === "upload" ? "uploads" : site.schedule}</Td>
            <Td label="Last crawl">{lastCrawl(site)}</Td>
            <Td label="Pages" numeric>
              {site.page_count}
            </Td>
            <Td label="Blocked" numeric>
              {site.blocked_count}
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

/** P2SR01: an upload site's last crawl is the crawl date of its last imported upload. */
export function lastCrawl(site: ContentSite): string {
  if (site.origin === "upload") {
    return site.last_crawled_on ? `crawled ${formatDate(site.last_crawled_on)}` : "no upload yet";
  }
  return site.last_crawl_at
    ? `${formatDate(site.last_crawl_at)} · ${site.last_crawl_status}`
    : "never";
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
    <form onSubmit={submit} className={cardClass("flex max-w-2xl flex-col gap-4")}>
      <h2 className="text-heading font-strong">Register a site</h2>
      <Field label="Start URL">{input("start_url")}</Field>
      <Field label="Name">{input("name")}</Field>
      <Field label="Publisher">{input("publisher")}</Field>
      <Field label="Licence basis">{input("licence_basis")}</Field>
      <fieldset className="flex flex-wrap gap-x-4 gap-y-2">
        <legend className="mb-2 text-ui font-strong">Tags</legend>
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
        <Notice tone="danger">{errorMessage(create.error)}</Notice>
      ) : null}
      {create.data ? (
        <Notice tone="success" role="status">
          Registered: it waits for a reviewer.
        </Notice>
      ) : null}
    </form>
  );
}
