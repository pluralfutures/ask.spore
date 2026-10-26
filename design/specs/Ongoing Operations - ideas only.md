# Ongoing operations between build phases — ideas only

**Status: ideas, not a procedure.** Written Oct 23, 2026 by the orchestrating session at the
owner's request. It describes what keeps the platform running after Phase 1c closes while no
build session is active, who does each thing, how often, and where the procedure already exists.
Where a procedure does not exist yet, the line says so and proposes one. Nothing here changes a
policy or a runbook; when the owner adopts a line, the policy or `infra/README.md` is the place
to write it down, and this file can be deleted or folded into an operations runbook.

The platform's posture: one Scaleway Instance in Paris, one operator (the owner), one client,
Compose-managed services (Caddy, web, API, worker, PostgreSQL, Redis, Authentik, RAGFlow with
its embedding service), Scaleway Generative APIs and Transactional Email as providers. There
is no monitoring stack and nothing pages anyone. The policies under `design/compliance/`
already promise several recurring activities; this file collects them in one calendar.

## 1. What runs by itself

These need no hand once the release is done. The check is that they are still running.

| What | Mechanism | Evidence it ran | Where to look |
| --- | --- | --- | --- |
| Retention purge of conversations past each tenant's retention (30-day cap; 0 means no history) | Daily worker job, `askspore_retention` role (P1b-14, migration 0040) | Audit event per run with row counts; worker log line | `audit_events`, `docker compose logs worker` |
| Downloads retention | Same job, `[retention] downloads_days` (capped at 365 since P1c-04) | Same | Same |
| Mail delivery | Worker `send_mail` jobs through Scaleway TEM | `jobs` rows reach `done`; no `worker.mail_not_configured` | Worker log, jobs table counts |
| Nightly volume backup | Owner's backup of PostgreSQL and RAGFlow volumes to Object Storage, object lock, 30-day retention (business continuity §2) | Archive per night | Scaleway console, `/srv/backups` |
| Nightly content-store copy | `/etc/cron.d/ask-spore-content`, 02:30 UTC, 14 copies kept (P1c-12) | `content-YYYYMMDD.tgz` per night | `/srv/backups/content` |
| TLS renewal | Caddy, automatic | Certificate dates | Browser padlock, Caddy log |
| Scheduled crawls | Worker, per site schedule | Crawl jobs and content events | Content console |
| Consent gate, RLS, allow-list checks at startup | In the application; the API refuses to start on an allow-list violation | Startup lines | API log at each restart |

Proposed weekly check (ten minutes, owner): the retention job ran every day (seven audit
events), both backups exist for every night (fourteen archives present, sizes plausible), no
failed `send_mail` job, no `worker.mail_not_configured`, disk below 80 percent
(`df -h /srv`), containers all `Up` (`docker compose ps`). Until there is monitoring (§7),
this is the only way anyone notices a silent failure.

## 2. Calendar of recurring owner work

| Cadence | Activity | Source of the obligation | Procedure |
| --- | --- | --- | --- |
| Weekly | The ten-minute health check above | None yet; proposed | §1 |
| Weekly, first weeks after launch | Read DMARC aggregate reports as counts only; move `p=none` to `p=quarantine` after seven clean days; `p=reject` after a clean period at quarantine | Paperwork checklist, `infra/README.md` "Mail domain policy" | Exists |
| Monthly | Image pin check: `python3 infra/scripts/image-digests.py --check`; read publishers' changelogs for moved tags; re-pin with `--write` in its own PR, CI green, deploy by script | Change management policy §9; `infra/README.md` "Image pins" | Exists |
| Monthly | Cost review: Scaleway invoice against the console's per-tenant cost report; token spend per model; TEM quota | Architecture §13; operator console | Report exists; no written cadence |
| Monthly | Dependency updates: `uv lock --upgrade` in `apps/api` and `packages/eval`, `pnpm update` in `apps/web`, tests and evals green, one PR | Change management policy | Proposed; no script |
| Quarterly | Credentials rotation: database roles, Authentik admin and bootstrap, RAGFlow service key, provider API keys, TEM key; `check-credentials.py` exits 0; api and worker restarted | `infra/README.md` "Credentials rotation" (P1c-03); offboarding pack row 6 for a leaver | Exists for DB and Authentik; provider keys and TEM key need a paragraph added |
| Quarterly | Restore test into the scratch project `askspore-restore`, counts compared, scratch torn down; recorded | Business continuity policy §3.2; `infra/README.md` "Restore test" | Exists |
| Quarterly | Access review: operators, Authentik admins, Scaleway IAM, SSH keys, GitHub collaborators; sign-off recorded | Access control policy §9; open question H2 (self-review while one person holds every role) | Policy exists; first date not set |
| Quarterly | Provider failover drill: switch the workspace default model by hand, time it, switch back | Business continuity policy §3.5 | Proposed |
| Quarterly | Eval re-run on the live corpus (eval set v1 and guardrails) against the baseline, even with no code change, to catch corpus drift and provider-side model changes | Release runbook section 5 pattern | Procedure exists in findings 1c §3.1.3; needs a "no release" variant |
| Half-yearly | Review `risk-register.md` and `open-questions.md`; close or re-date each row | Compliance guide | Documents exist |
| Annually | Vendor review: DPA version, security report, region, retention terms, ZDR status for Scaleway, OpenRouter (if used), Mailgun (if used) | Vendor management policy §7 | Policy exists |
| Annually | Incident tabletop exercise against `incident-runbook.md` | Client DPA row "annual tabletop" | Runbook exists; exercise not scheduled |
| Annually | Consent notice review with counsel; a reviewed version is a new `config/consent/vN.md` that users re-accept | Consent notice v1 summary | Mechanism exists (P1b-13) |
| Annually | Penetration test (architecture §13 budget line) | Architecture; SOC 2 expectation | Not planned |
| On each event | Takedown requests within 10 working days; personal-data requests within 30 days | Consent notice Part B; content console takedown queue | Queue exists |

## 3. Deploying without a build phase

Small changes will still happen between phases (a pin, a dependency, a wording fix, a backlog
follow-up such as the invitation resend limit). The pattern that worked in 1c, scaled down:

1. One branch per change, referencing a backlog line or spec item in the commit; CI green
   (unit, migration, Playwright, deploy dry run).
2. Owner merges to `main`.
3. On the Instance: `git pull` on `main`, `infra/scripts/deploy.sh --dry-run`, then the full
   script with the public URL. The script checks pins and credentials, builds, migrates,
   recreates api and worker, polls `/healthz`, prints dataset counts.
4. If the change touched the answer path (prompt, model, retrieval settings, orchestrator):
   the eval and guardrail runs before the merge, on a temporary api, as in release section 5.
5. One line in the current findings file or a small `ops-log.md` (proposed): date, commit,
   what changed, dataset counts before and after.

A rollback is `git checkout <previous commit>` on the live tree and the deploy script again;
Alembic downgrades exist but have never been run in production and should be tested in the
scratch project first if ever needed.

## 4. Supporting the client

Nothing is built for support beyond the tenant admin's own pages. Proposed minimum:

- **Contact path.** A support address on the client's onboarding pack, answered by the owner.
  Response targets stated in the pack (the client DPA promises breach notice timelines;
  ordinary support has none).
- **What the owner can see.** Audit events (metadata), job states, content console, the
  cost report, the terminated-tenants list. Not conversations: the consent notice says staff
  read a conversation only on the employer's request for support on it, time-boxed and logged.
  That feature does not exist; until it does, the honest answer to a "why did it say that"
  ticket is to ask the user to share the conversation text themselves, and to record the
  request in the support log. Building the time-boxed access is a Phase 2 idea (Phase 2 ideas
  §4.2).
- **Account tasks** the tenant admin can do alone: invite, resend, remove a user, set
  retention, edit the workspace prompt. The operator does: enable modes and entitlements,
  verified domains, SSO sources (with the client's secrets entered in the console), tag
  packages, suspend and terminate.
- **A changelog** for the client: one line per deployed change that is visible to users
  (Phase 2 ideas §4.1 proposes a public changelog; a private email is enough for one client).

## 5. Incidents

`design/compliance/incident-runbook.md` exists with severities, steps, notification timelines
and templates, and playbooks (suspected cross-tenant leak, provider outage, lost host). What
is missing for it to work with nobody watching:

- **Detection.** Today: a user report, or the owner noticing. The weekly check (§1) is the
  floor; monitoring (§7) is the proposal.
- **Containment tooling** is in place: `docker compose stop api`, Caddy route block, cache
  clear through `app.core.cache` tooling, the isolation test suite against a schema copy.
- **Evidence export** is a manual psql query on `audit_events` plus `docker compose logs`
  to the document store. A small script that exports a time window as CSV, metadata only,
  would make the runbook's step 4 a single command (proposed, half a day).
- **Key person.** Business continuity §3.8: the owner is the only operator; a sealed access
  procedure for a deputy is to be kept in the document store. Confirm it exists before the
  first client user is invited.

## 6. Growth without a build phase

Operations the operator does in the console, no code:

- **A new tenant** (if a second client signs before Phase 2): create the tenant, verified
  domains, invite the first admin, tag package, retention, modes. Dataset IDs come from the
  package, never from the client; nothing else changes. The termination purge and certificate
  are built. The DPA and sub-processor list go out with the onboarding pack.
- **New content** for an existing package: register a source or site, review and approve
  (self-approval allowed and audited while there is one internal user), ingest; the register
  records licence, review date and the TDM check. Dataset counts are the sanity check after
  every ingest and withdrawal.
- **A new prompt** is never an operator action: a new version file, an eval run, a PR.
- **A new model** is never an operator action either: `config/models.toml`, the allow-list,
  an eval baseline, the privacy notice's model list, a PR.

## 7. Observability (proposal; not in any policy yet)

The gap most likely to hurt: nothing alerts on a stopped container, a full disk, a failed
backup, a stuck retention job, an expired certificate, or an error rate. Options in increasing
size:

1. **Cron-and-mail.** A root cron script on the Instance that runs the §1 checks every hour
   and sends one email through TEM only when something is wrong (counts and names only). A
   day of work, no new service, no new vendor. Recommended as the first step.
2. **Uptime check from outside.** A third-party or Scaleway uptime probe on
   `https://askspore.myceliumgastronomy.com/healthz` with email alerting; covers the host and
   Caddy dying, which option 1 cannot report. Vendor review needed if third-party (it sees only
   the health endpoint, no personal data).
3. **The monitoring stack** of the two-host deployment (Phase 2 ideas §3.1): metrics,
   dashboards, alert rules, log aggregation with the no-bodies rule enforced at the shipper.
   A build item.

Whatever is chosen, the no-request-bodies rule applies to every alert and every log shipped
off the host.

## 8. Cost of standing still

Fixed: the Instance (shared 8 vCPU, 32 GB, 100 GB Block Storage), Block Storage snapshots and
the Object Storage backup bucket, the domain and DNS. Variable: Scaleway Generative APIs tokens
per question (shown per tenant in the console cost report), TEM messages (free tier likely
sufficient for one client), eval re-runs (a full eval set v1 run plus guardrails is a known
token cost from the Phase 1b and 1c records; budget one per quarter). Nothing else is billed.
The owner's time is the main cost: about one hour a week on the checks, half a day a quarter
on the rotation, restore test and access review together, and the time to answer the client.

## 9. What would make this file unnecessary

An `operations-runbook.md` (or a section in `infra/README.md`) adopted by the owner with the
calendar from §2, the weekly check from §1 and the deploy pattern from §3; the business
continuity, access control and change management policies updated to point at it; and option 1
or 2 of §7 running. That is one short session's work plus owner review, and could be the first
thing done after the Phase 1c close.
