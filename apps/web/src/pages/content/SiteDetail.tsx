import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { contentApi } from "../../api/client";
import type { ContentSiteDetail, SitePage } from "../../api/types";
import {
  ALLOW_DECISIONS,
  SCHEDULES,
  canReview,
  errorMessage,
  pageReason,
  parsePatterns,
} from "../../lib/content";
import { formatDate } from "../../lib/format";
import { Button } from "../../ui/Button";
import { EmptyState, Skeleton } from "../../ui/States";
import { LINK } from "../../ui/link";
import { Field } from "../../ui/Field";
import { Input, Select, Textarea } from "../../ui/Input";
import { Notice } from "../../ui/Notice";
import { StatusBadge } from "../../ui/Badge";
import { Card } from "../../ui/Card";
import { Table, Td, Th } from "../../ui/Table";

// One site (P1b-04, P1b-05): its settings, allow decision and last crawl, every page a
// crawl met (blocked ones with the reason), and the reviewer's actions: approve or
// reject, scope rules, schedule and page budget, the special-category whitelist, and
// withdrawing the whole site (P1c-14) and reinstating a withdrawn one (P2A-12). Any
// content role may ask for a crawl now.
export function SiteDetail({ roles }: { roles: string[] }) {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const site = useQuery({ queryKey: ["content", "site", id], queryFn: () => contentApi.site(id) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["content"] });
  const crawl = useMutation({ mutationFn: () => contentApi.crawl(id), onSuccess: refresh });
  if (site.error) return <Notice tone="danger">{errorMessage(site.error)}</Notice>;
  if (!site.data) return <Skeleton />;
  const data = site.data;
  return (
    <section className="flex flex-col gap-4">
      <SiteSummary site={data} />
      {data.status === "approved" ? (
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={() => crawl.mutate()} disabled={crawl.isPending}>
            Crawl now
          </Button>
          {crawl.data ? <span>Queued.</span> : null}
          {errorMessage(crawl.error) ? (
            <Notice tone="danger">{errorMessage(crawl.error)}</Notice>
          ) : null}
        </div>
      ) : null}
      {canReview(roles) ? <SiteReview site={data} /> : null}
      <PageTable pages={data.pages} />
    </section>
  );
}

export function SiteSummary({ site }: { site: ContentSiteDetail }) {
  return (
    <Card title={site.name} className="gap-1">
      <p>
        {site.start_url} · {site.publisher} · {site.licence_basis} · {site.tags.join(", ")}
      </p>
      <p>
        Status: <StatusBadge kind="site" status={site.status} /> · allow decision:{" "}
        <span data-testid="allow-decision">
          {ALLOW_DECISIONS[site.allow_decision] ?? site.allow_decision}
        </span>
      </p>
      <p>
        Schedule {site.schedule} · budget {site.max_pages} pages · last crawl{" "}
        {site.last_crawl_at
          ? `${formatDate(site.last_crawl_at)} (${site.last_crawl_status})`
          : "never"}
        {site.next_crawl_at ? ` · next ${formatDate(site.next_crawl_at)}` : ""}
      </p>
      <p>
        {site.page_count} live pages · {site.blocked_count} blocked
      </p>
      <p>
        Scope: crawl {site.allow_patterns.join(", ") || "everything"}; never{" "}
        {site.deny_patterns.join(", ") || "—"}; special-category whitelist{" "}
        {site.special_category_allow.join(", ") || "—"}
      </p>
      {site.review_note ? <p>Reviewer's note: {site.review_note}</p> : null}
      {site.status === "withdrawn" ? (
        <Notice tone="danger" data-testid="site-withdrawn">
          Withdrawn {formatDate(site.withdrawn_at)}: {site.withdrawal_reason}. Never crawled again
          unless a reviewer reinstates it; every page is withdrawn.
        </Notice>
      ) : null}
      {site.status === "proposed" && site.withdrawn_at ? (
        <Notice tone="warning" data-testid="site-reinstated">
          Reinstated after a withdrawal on {formatDate(site.withdrawn_at)} ({site.withdrawal_reason}
          ). Not crawled until a reviewer approves it again; pages taken down stay out.
        </Notice>
      ) : null}
    </Card>
  );
}

export function PageTable({ pages }: { pages: SitePage[] }) {
  if (pages.length === 0) return <EmptyState title="No pages crawled yet." />;
  return (
    <Table>
      <thead>
        <tr>
          <Th>Page</Th>
          <Th>State</Th>
          <Th>Why</Th>
          <Th>Published</Th>
          <Th>Fetched</Th>
        </tr>
      </thead>
      <tbody>
        {pages.map((page) => (
          <tr key={page.url}>
            <Td label="Page" className="break-all">
              {page.source_id ? (
                <Link to={`/content/sources/${page.source_id}`} className={LINK}>
                  {page.url}
                </Link>
              ) : (
                page.url
              )}
            </Td>
            <Td label="State">
              <StatusBadge kind="page" status={page.state} />
            </Td>
            <Td label="Why">{pageReason(page.reason, page.special_category)}</Td>
            <Td label="Published">{page.published_on ? formatDate(page.published_on) : "—"}</Td>
            <Td label="Fetched">{formatDate(page.fetched_at)}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function SiteReview({ site }: { site: ContentSiteDetail }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["content"] });
  const [note, setNote] = useState("");
  const [allow, setAllow] = useState(site.allow_patterns.join("\n"));
  const [deny, setDeny] = useState(site.deny_patterns.join("\n"));
  const [schedule, setSchedule] = useState(site.schedule);
  const [maxPages, setMaxPages] = useState(String(site.max_pages));
  const [whitelist, setWhitelist] = useState(site.special_category_allow.join("\n"));
  const approve = useMutation({
    mutationFn: () => contentApi.approveSite(site.id, note.trim() || null),
    onSuccess: refresh,
  });
  const reject = useMutation({
    mutationFn: () => contentApi.rejectSite(site.id, note),
    onSuccess: refresh,
  });
  const save = useMutation({
    mutationFn: () =>
      contentApi.siteSettings(site.id, {
        allow_patterns: parsePatterns(allow),
        deny_patterns: parsePatterns(deny),
        schedule: schedule as "none" | "weekly" | "monthly",
        max_pages: Number(maxPages),
      }),
    onSuccess: refresh,
  });
  const saveWhitelist = useMutation({
    mutationFn: () => contentApi.siteWhitelist(site.id, parsePatterns(whitelist)),
    onSuccess: refresh,
  });
  const [reason, setReason] = useState("");
  const withdraw = useMutation({
    mutationFn: () => contentApi.withdrawSite(site.id, reason),
    onSuccess: refresh,
  });
  const [reinstateNote, setReinstateNote] = useState("");
  const reinstate = useMutation({
    mutationFn: () => contentApi.reinstateSite(site.id, reinstateNote),
    onSuccess: refresh,
  });
  const error =
    errorMessage(reinstate.error) ??
    errorMessage(approve.error) ??
    errorMessage(reject.error) ??
    errorMessage(save.error) ??
    errorMessage(saveWhitelist.error) ??
    errorMessage(withdraw.error);
  return (
    <Card title="Review" level={3}>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      {site.status === "proposed" ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Note (required to reject)">
            <Input value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <Button variant="primary" onClick={() => approve.mutate()}>
            Approve and crawl
          </Button>
          <Button variant="secondary" onClick={() => reject.mutate()} disabled={!note.trim()}>
            Reject
          </Button>
        </div>
      ) : null}
      {site.status === "approved" ? (
        <WithdrawSite
          reason={reason}
          onReason={setReason}
          onWithdraw={() => withdraw.mutate()}
          pending={withdraw.isPending}
        />
      ) : null}
      {site.status === "withdrawn" ? (
        <ReinstateSite
          note={reinstateNote}
          onNote={setReinstateNote}
          onReinstate={() => reinstate.mutate()}
          pending={reinstate.isPending}
        />
      ) : null}
      {site.status !== "rejected" && site.status !== "withdrawn" ? (
        <div className="grid gap-2 md:grid-cols-2">
          <Field label="Paths to crawl (one per line)">
            <Textarea value={allow} onChange={(e) => setAllow(e.target.value)} />
          </Field>
          <Field label="Paths never to crawl">
            <Textarea value={deny} onChange={(e) => setDeny(e.target.value)} />
          </Field>
          <Field label="Schedule">
            <Select value={schedule} onChange={(e) => setSchedule(e.target.value)}>
              {SCHEDULES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Page budget">
            <Input value={maxPages} onChange={(e) => setMaxPages(e.target.value)} />
          </Field>
          <Button variant="secondary" className="w-fit" onClick={() => save.mutate()}>
            Save settings
          </Button>
          <span />
          <Field label="Special-category whitelist (paths, one per line, e.g. /health/*)">
            <Textarea value={whitelist} onChange={(e) => setWhitelist(e.target.value)} />
          </Field>
          <Button
            variant="secondary"
            className="w-fit self-end"
            onClick={() => saveWhitelist.mutate()}
          >
            Save whitelist
          </Button>
        </div>
      ) : null}
    </Card>
  );
}

// P1c-14: retires the site (no further crawls) and withdraws every page everywhere.
export function WithdrawSite({
  reason,
  onReason,
  onWithdraw,
  pending,
}: {
  reason: string;
  onReason: (value: string) => void;
  onWithdraw: () => void;
  pending: boolean;
}) {
  return (
    <div data-testid="withdraw-site" className="flex flex-wrap items-end gap-2">
      <Field label="Reason for withdrawing the site">
        <Input value={reason} onChange={(e) => onReason(e.target.value)} />
      </Field>
      <Button variant="secondary-danger" onClick={onWithdraw} disabled={pending || !reason.trim()}>
        Withdraw site
      </Button>
      <span className="text-fg-muted">
        Every page leaves every dataset, and the site is never crawled again.
      </span>
    </div>
  );
}

// P2A-12 (a): back to proposed with the reviewer's note. Never approved here: the site
// needs a fresh approval before any crawl, and pages taken down stay out.
export function ReinstateSite({
  note,
  onNote,
  onReinstate,
  pending,
}: {
  note: string;
  onNote: (value: string) => void;
  onReinstate: () => void;
  pending: boolean;
}) {
  return (
    <div data-testid="reinstate-site" className="flex flex-wrap items-end gap-2">
      <Field label="Note for reinstating the site">
        <Input value={note} onChange={(e) => onNote(e.target.value)} />
      </Field>
      <Button variant="secondary" onClick={onReinstate} disabled={pending || !note.trim()}>
        Reinstate site
      </Button>
      <span className="text-fg-muted">
        The site goes back to proposed and needs a fresh approval before any crawl. Pages taken down
        stay out; its other pages come back as new versions.
      </span>
    </div>
  );
}
