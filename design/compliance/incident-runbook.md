# Incident Runbook and Breach Notification — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [security contact email], [takedown contact email], [incident lead phone], [counsel name and contact], [Client], [Client incident contact], [supervisory authority], [document store], [date] |
| To finalise, the owner must | (1) name the incident lead and deputy and fill in the contacts; (2) confirm the DPA notification window (clause 9.1, [48] hours) with counsel; (3) identify our lead [supervisory authority] and its notification form; (4) collect each client's incident contact at onboarding (`onboarding-pack.md`); (5) run the first tabletop and record it; (6) have counsel review the templates in §7. |

This runbook implements `policy-incident-response.md`.

---

## 1. Ground rules

- **Never copy bodies into the incident record.** No question, answer, prompt, excerpt, token, sign-in link or header goes into tickets, chat, email or this repository. Record IDs, counts, times, error codes and audit event IDs only. This holds during an incident too.
- Contain first, then investigate. When in doubt, treat an event as an incident and close it later.
- Every incident gets a log entry (§6) the same day, even if it turns out to be nothing.

## 2. Roles

| Role | Who today | Duties |
| --- | --- | --- |
| Incident lead | The owner ([incident lead phone]) | Declares severity, decides containment, owns notifications |
| Deputy | [ ] | Takes over when the lead is unreachable for 2 hours |
| Engineering | The owner, with a Claude coding session for fixes | Containment, evidence, fix, verification |
| Counsel | [counsel name and contact] | Advises on notification duties and wording |
| Privacy contact | privacyanddata@myceliumgastronomy.com | Breach assessment, regulator contact |
| Scaleway support | Scaleway console ticket | Infrastructure, Generative APIs, Transactional Email |
| Client contact | [Client incident contact] per client | Receives the processor notice |

## 3. Severity

| Level | Meaning | Examples | Response |
| --- | --- | --- | --- |
| SEV1 | Confirmed or likely exposure of client data to an unauthorised party, or of data across tenants; secret compromise with access to data | Cross-tenant read; database or backup exposed; leaked Scaleway key with project access | Start at once; incident lead on call until contained; notification clock running |
| SEV2 | Control failure without known exposure; outage of the whole service | Bodies found in logs; RAGFlow index unusable; Scaleway inference down | Same working day |
| SEV3 | Degraded service or a single-user issue | One user's link scanned; a takedown request with legal threat | Within 2 working days |

A personal data breach (Art. 4(12)) is any SEV1, and some SEV2 (for example bodies in logs readable by someone who should not read them). Decide this explicitly and record why.

## 4. Steps for every incident

1. **Detect.** Sources today: a report to [security contact email], a client or user, an operator notice, a failing test or eval, the owner noticing. There is no automated alerting yet (monitoring stack in backlog).
2. **Triage** (within 1 hour for SEV1). What happened, which tenants, which data categories, since when. Set the severity. Start the log entry. Note the time we became aware: this starts the clocks in §5.
3. **Contain.** Use the playbook in §8. Options available today: stop the API container (`docker compose stop api`), switch sign-in links off for a tenant in the operator console, disable a tenant's entitlements, revoke an operator (`ask-spore operators revoke`), rotate a secret, block a route in Caddy.
4. **Preserve evidence.** Export the relevant `audit_events` rows (metadata) and container logs to [document store]/incidents/[date]/. The audit table is append-only; do not attempt to change it.
5. **Eradicate.** Fix the cause in code through a reviewed PR with a test that proves the negative case.
6. **Recover.** Restore service; run the isolation tests and, for answer-path changes, the eval and guardrail evals; clear affected tenants' answer caches.
7. **Notify** per §5.
8. **Review** within 10 working days: root cause, what worked, actions with owners, update `risk-register.md`.

## 5. Notification timelines

| Our role | Who we notify | When | Basis |
| --- | --- | --- | --- |
| Processor (client user data: accounts, sign-in events, conversations, downloads, audit of its users) | The affected client's incident contact | Without undue delay and within **[48] hours** of becoming aware | Client DPA clause 9.1; Art. 33(2) |
| Processor | Supervisory authority, data subjects | **We do not notify them.** The client, as controller, decides | Art. 33(1), 34 |
| Controller (corpus, our logs, operator accounts, requests sent to us) | [supervisory authority] | Within **72 hours** of becoming aware, unless the breach is unlikely to result in a risk to people; give reasons for any delay; may be given in phases | Art. 33(1), (4) |
| Controller | Affected people | Without undue delay where the breach is likely to result in a **high** risk to them | Art. 34 |
| Either | Scaleway, OpenRouter | When their service is involved, so they can preserve their evidence | Their DPAs |

Record a breach in the log (§6) whether or not it is notified (Art. 33(5)).

## 6. Incident log

Kept at [document store]/incidents/log. One row per incident:

| Field | Content |
| --- | --- |
| ID | INC-[year]-[number] |
| Opened / aware / contained / closed | Times in UTC |
| Severity | SEV1–3 and why |
| Summary | Metadata only |
| Tenants and data categories | Tenant slugs, categories, approximate number of people and records |
| Personal data breach? | Yes / no, with reasoning; our role (processor / controller) |
| Notifications | Who, when, reference |
| Root cause and fix | PR and commit |
| Follow-up actions | Owner, due date |

## 7. Notification templates

### 7a. Processor notice to a client

> Subject: Security incident notice — SporeBot — INC-[ ]
>
> Dear [Client incident contact],
>
> Under clause 9 of our Data Processing Agreement, we are notifying you of a personal data breach affecting data we process on your behalf. This is our [first / updated] notice; we will update you as we learn more.
>
> 1. **What happened:** [plain description, no question or answer text].
> 2. **When:** started [date, time UTC] (or "not yet known"); we became aware on [date, time UTC]; contained on [date, time UTC].
> 3. **Categories and approximate number of people concerned:** [for example: users of your organisation, about [n]].
> 4. **Categories and approximate number of records:** [for example: conversation records, about [n]; account records, [n]].
> 5. **Likely consequences:** [ ].
> 6. **Measures taken or proposed**, including to reduce possible adverse effects: [ ].
> 7. **What we suggest you do:** [for example: tell affected users to sign out and request a new link].
> 8. **Contact:** privacyanddata@myceliumgastronomy.com, [incident lead phone].
>
> As controller, you decide whether to notify your supervisory authority and the people concerned. We will give you the information and help you need for that.
>
> Estefania Simon-Sasyk y Otro CB

### 7b. Controller notification to the supervisory authority (summary to transfer into the authority's form)

| Field | Entry |
| --- | --- |
| Controller | Estefania Simon-Sasyk y Otro CB, Hermanos Otamendi kalea, 11, 20014 San Sebastián, Gipuzkoa, Spain; contact privacyanddata@myceliumgastronomy.com |
| Nature of the breach | Confidentiality / integrity / availability; [description] |
| Data subjects | Categories (for example people named in corpus sources; our operators) and approximate number |
| Records | Categories and approximate number |
| Time | Start, awareness, containment |
| Likely consequences | [ ] |
| Measures taken and proposed | [ ] |
| Data subjects informed? | Yes / no / planned, and why |
| Reasons for delay beyond 72 hours | [if any] |
| Cross-border | [lead authority, other affected Member States] |

### 7c. Notice to affected people

> Subject: Important information about your personal data
>
> We are writing because of an incident that affected personal data about you held by Estefania Simon-Sasyk y Otro CB, which runs SporeBot.
>
> **What happened:** [plain description].
> **What data was involved:** [ ].
> **What this could mean for you:** [ ].
> **What we have done:** [ ].
> **What you can do:** [ ].
>
> If you have questions, contact privacyanddata@myceliumgastronomy.com. You also have the right to complain to [supervisory authority].

## 8. Playbooks

### 8.1 Suspected cross-tenant leak (SEV1)

1. **Freeze.** Stop the API container, or block the affected route in Caddy if the leak is narrow. Keep PostgreSQL and Redis running for evidence.
2. Clear the answer cache for the affected tenants (only through `app.core.cache` tooling, never direct Redis commands in code).
3. Investigate from the audit log: `chat.query`, `download`, `auth.login` events for the tenants and window concerned; workspace and tag changes (`operator.workspace_tags_changed`, findings F2 shows how a wrong save looks).
4. Check RLS: run the isolation suite (`test_schema`, `test_tenancy`, `test_cache`) against the live schema copy.
5. Notify each affected client within the DPA window (§5). Both the tenant whose data was exposed and the tenant that saw it are affected.
6. Restart only after a fix with a negative-case test.

### 8.2 Bodies found in logs (SEV2, may be a breach)

1. Identify the log line and code path; stop the container if it continues.
2. Delete the affected log files on the Instance after copying their metadata (not the text) into the incident record. If the logs were sent anywhere else, list where.
3. Fix with a test proving the log line carries no body (CLAUDE.md rule); review `app.core.logging` and ErrorBoundary.
4. Assess whether anyone other than operators read them. If only our operators had access, record the reasoning for "no risk" and notify clients only if counsel advises.

### 8.3 Credential or key leak (SEV1 if the key gives data access)

Rotate, then revoke the old secret, then check the audit trail and provider logs for its use.

| Secret | Where it lives today | Rotate |
| --- | --- | --- |
| Scaleway IAM API keys (project, Generative APIs) | Env files on the Instance | Scaleway console → IAM → new key, update env, restart, delete old key |
| Scaleway Transactional Email SMTP credential | `infra/authentik/.env` | New IAM key scoped to Transactional Email, update Authentik, send a test link |
| OpenRouter API key | Env file (external models off, key may be absent) | OpenRouter dashboard; revoke |
| Authentik API token (provisioner) and client secret | Env files | Authentik admin → tokens; update the API env |
| Authentik user sessions and access tokens | Authentik | End sessions for affected users; revoke tokens |
| RAGFlow service key | Env file | RAGFlow admin; update the API env |
| PostgreSQL passwords | Env files | `ALTER ROLE`; update env |
| SSH keys | Instance | Remove from `authorized_keys`, Scaleway security group review |

Secrets are not yet in Scaleway Secret Manager (backlog); after an incident, check the repository history for accidental commits (`run_secret_scanning` or a manual search).

### 8.4 Model provider outage (SEV2)

- Scaleway Generative APIs down: no answers are possible today. The Mistral provider is configured but inactive and has no DPA in force, so it is not a fallback. Show the outage to users; follow Scaleway's status page. The owner chose OpenRouter, routed only to EU-served models with zero data retention, as the future backup (Oct 21, 2026); it is not built and needs the design and contract changes listed in `policy-business-continuity.md` before it may be used for a tenant without the external-models entitlement.
- External model unavailable or spend cap reached: new conversations fall back to the workspace default EU model with a notice (`model.fallback` audit event). No action unless it persists.
- Do not switch to a provider that is not on the allow-list or in `sub-processors.md`.

### 8.5 RAGFlow index corruption or loss (SEV2)

1. Answers abstain or fail; confirm with the eval set on the default model.
2. Restore the RAGFlow volumes from the latest backup (owner-run backups to Object Storage; the restore procedure is not yet tested), or rebuild by re-running the manifests (`ask-spore ingest`), which re-parses from the content store.
3. Check dataset document counts against the source register; re-run the eval set before reopening.

### 8.6 Mail scanner consumes links, or link abuse (SEV3, SEV1 if an account was taken over)

- A scanner opening a link cannot sign in: only the button's POST consumes the token. If users report "link already used", check for a scanner that executes pages and follow the IT note in `onboarding-pack.md`.
- Suspected mailbox takeover: switch sign-in links off for the tenant (operator console), end the user's Authentik sessions, notify the client. From Phase 1b the tenant can use SSO instead (P1b-07).
- Floods of link requests: the per-user limit (5 per window) holds; per-IP limits from Phase 1b (P1b-08); block the source in Caddy meanwhile.

### 8.7 External-model vendor breaks zero data retention (SEV1 if confirmed)

1. Disable external models for every tenant in the operator console (audited).
2. Ask OpenRouter for the facts in writing; check the TIA triggers (`transfer-impact-assessment.md` §9).
3. Notify clients that had the mode enabled within the DPA window.
4. Re-enable only after the paperwork gate is re-checked (`paperwork-checklist.md`).

### 8.8 Takedown emergency (SEV2 or SEV3)

A court order, a credible legal threat, or a licence breach we find ourselves.

1. Withdraw the source at once: today, delete the document from every RAGFlow dataset it is in by hand, clear the answer caches of tenants whose workspaces include those tags, and set `downloadable` off; from Phase 1b, the `withdraw_source` job does this with an audit trail (P1b-03).
2. Record the request, our decision and the time in the takedown log.
3. Answer the requester from [takedown contact email] within the window (10 working days; immediate for licence breaches).
4. If a downloadable file was wrongly flagged, list the `download` audit events for it to know how many copies left the platform.

## 9. Tabletop

Once a year, and before the SOC 2 observation window starts: walk through one SEV1 scenario (8.1 or 8.3) end to end, with the clocks. Record date, participants, scenario, gaps found and actions in [document store]/incidents/tabletops/. The first tabletop is not yet scheduled: [date].
