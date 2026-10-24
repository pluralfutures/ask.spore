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
import { LINK } from "../../ui/link";

// One site (P1b-04, P1b-05): its settings, allow decision and last crawl, every page a
// crawl met (blocked ones with the reason), and the reviewer's actions: approve or
// reject, scope rules, schedule and page budget, the special-category whitelist, and
// withdrawing the whole site (P1c-14). Any content role may ask for a crawl now.
export function SiteDetail({ roles }: { roles: string[] }) {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const site = useQuery({ queryKey: ["content", "site", id], queryFn: () => contentApi.site(id) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["content"] });
  const crawl = useMutation({ mutationFn: () => contentApi.crawl(id), onSuccess: refresh });
  if (site.error) return <p className="text-danger">{errorMessage(site.error)}</p>;
  if (!site.data) return <p>Loading…</p>;
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
            <span className="text-danger">{errorMessage(crawl.error)}</span>
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
    <div className="flex flex-col gap-1 rounded-control bg-surface p-3">
      <h2 className="text-heading font-strong">{site.name}</h2>
      <p>
        {site.start_url} · {site.publisher} · {site.licence_basis} · {site.tags.join(", ")}
      </p>
      <p>
        Status: <strong>{site.status}</strong> · allow decision:{" "}
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
        <p data-testid="site-withdrawn" className="text-danger-strong">
          Withdrawn {formatDate(site.withdrawn_at)}: {site.withdrawal_reason}. Never crawled again;
          every page is withdrawn.
        </p>
      ) : null}
    </div>
  );
}

export function PageTable({ pages }: { pages: SitePage[] }) {
  if (pages.length === 0) return <p className="text-fg-muted">No pages crawled yet.</p>;
  return (
    <table className="w-full rounded-control bg-surface text-left">
      <thead>
        <tr className="border-b">
          <th className="p-2">Page</th>
          <th className="p-2">State</th>
          <th className="p-2">Why</th>
          <th className="p-2">Published</th>
          <th className="p-2">Fetched</th>
        </tr>
      </thead>
      <tbody>
        {pages.map((page) => (
          <tr key={page.url} className="border-b">
            <td className="p-2 break-all">
              {page.source_id ? (
                <Link to={`/content/sources/${page.source_id}`} className={LINK}>
                  {page.url}
                </Link>
              ) : (
                page.url
              )}
            </td>
            <td className="p-2">{page.state}</td>
            <td className="p-2">{pageReason(page.reason, page.special_category)}</td>
            <td className="p-2">{page.published_on ? formatDate(page.published_on) : "—"}</td>
            <td className="p-2">{formatDate(page.fetched_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
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
  const error =
    errorMessage(approve.error) ??
    errorMessage(reject.error) ??
    errorMessage(save.error) ??
    errorMessage(saveWhitelist.error) ??
    errorMessage(withdraw.error);
  return (
    <div className="flex flex-col gap-3 rounded-control bg-surface p-3">
      <h3 className="font-strong">Review</h3>
      {error ? <p className="text-danger">{error}</p> : null}
      {site.status === "proposed" ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col">
            Note (required to reject)
            <input value={note} onChange={(e) => setNote(e.target.value)} className="border px-1" />
          </label>
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
      {site.status !== "rejected" && site.status !== "withdrawn" ? (
        <div className="grid gap-2 md:grid-cols-2">
          <label className="flex flex-col">
            Paths to crawl (one per line)
            <textarea
              value={allow}
              onChange={(e) => setAllow(e.target.value)}
              className="border p-1"
            />
          </label>
          <label className="flex flex-col">
            Paths never to crawl
            <textarea
              value={deny}
              onChange={(e) => setDeny(e.target.value)}
              className="border p-1"
            />
          </label>
          <label className="flex flex-col">
            Schedule
            <select
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              className="border"
            >
              {SCHEDULES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col">
            Page budget
            <input
              value={maxPages}
              onChange={(e) => setMaxPages(e.target.value)}
              className="border px-1"
            />
          </label>
          <Button variant="secondary" className="w-fit" onClick={() => save.mutate()}>
            Save settings
          </Button>
          <span />
          <label className="flex flex-col">
            Special-category whitelist (paths, one per line, e.g. /health/*)
            <textarea
              value={whitelist}
              onChange={(e) => setWhitelist(e.target.value)}
              className="border p-1"
            />
          </label>
          <Button
            variant="secondary"
            className="w-fit self-end"
            onClick={() => saveWhitelist.mutate()}
          >
            Save whitelist
          </Button>
        </div>
      ) : null}
    </div>
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
      <label className="flex flex-col">
        Reason for withdrawing the site
        <input value={reason} onChange={(e) => onReason(e.target.value)} className="border px-1" />
      </label>
      <Button variant="secondary-danger" onClick={onWithdraw} disabled={pending || !reason.trim()}>
        Withdraw site
      </Button>
      <span className="text-fg-muted">
        Every page leaves every dataset, and the site is never crawled again.
      </span>
    </div>
  );
}
