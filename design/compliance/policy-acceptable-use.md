# Acceptable Use Policy (Staff and Contractors) — Draft

**DRAFT for owner and counsel review, Oct 22, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 22, 2026 |
| Author | Drafted for owner review (gap found in the Phase 1b document set: the compliance guide's SOC 2 policy list names "acceptable use"; owner request of Oct 22, 2026) |
| Placeholders | [security lead name], [security contact email], [password manager], [document store], [5] (screen-lock minutes), [24] (hours to report an incident), [date] |
| To finalise, the owner must | (1) fill in the placeholders; (2) confirm the device rules in §3 match what is in use; (3) have counsel check §7 (monitoring) against Spanish employment and privacy law before any employee or contractor signs it; (4) approve and sign; (5) have every person with access sign §9 before access is granted (`policy-access-control.md`). |

---

## 1. Purpose and scope

How people who work on SporeBot may use its systems, its data and their own devices. It applies to everyone with access to production, the repository, the operator or content consoles, vendor consoles (Scaleway, OpenRouter, the mail provider), the document store, or client files: today the owner; later any employee or contractor.

It is the internal counterpart of the customers' acceptable-use rules in `terms-of-service.md` §5, and sits under `policy-information-security.md`.

## 2. Data we protect

| Class | Examples | Rule of thumb |
| --- | --- | --- |
| Client confidential | Questions, answers, conversations, client-supplied files, workspace instructions | Stays in the platform; never copied elsewhere except as this policy allows |
| Personal data | User accounts, audit records, request-log entries, people named in sources | Only for the purpose it was collected for |
| Secrets | API keys, service keys, database credentials, SSO client secrets, SAML keys | Never leaves the secret store |
| Licensed content | Third-party reports in the library | Used only as the licence allows |
| Internal | Code, design documents, synthetic fixtures | May sit in the repository |

## 3. Devices and accounts

1. Work only on devices with **full-disk encryption**, a screen lock of [5] minutes or less, automatic operating-system security updates and a supported operating system.
2. Use **multi-factor authentication** on every account that offers it: GitHub, Scaleway, OpenRouter, the mail provider, the document store, Authentik.
3. Keep passwords in [password manager]; never reuse them; never share an account.
4. Lost or stolen device: report to [security contact email] at once; credentials on it are rotated the same day.
5. Personal use of work devices is allowed if it does not weaken these rules (no untrusted software, no sharing the device).

## 4. Handling client data

1. **No client data outside the platform**, except: client-supplied files received for registration (on encrypted devices only, deleted within 30 days after the contract ends or earlier on withdrawal or request); exports a client asked for (sent by an agreed channel, then deleted); and incident evidence (metadata only, in [document store]).
2. **Never debug or test with real queries or client documents.** Tests use synthetic content under `packages/eval/fixtures/` (CLAUDE.md).
3. **Never read conversations** except when the client asks for support on a specific conversation; such access is time-boxed and logged.
4. **No client data, real queries, secrets or `.env` files in the repository, issues, pull requests, chat tools or email**, except client-supplied files arriving by the channels in `policy-content-sourcing.md` §5.1.
5. **AI tools.** Client data and real queries may be processed only by the platform itself, through the model providers listed in `sub-processors.md`. Coding assistants (including Claude Code sessions) may work on code, design documents and synthetic fixtures, but are never given production secrets, client documents, real queries or exports.
6. **Logs and screenshots** of the product must not show client content; use synthetic tenants for demos.

## 5. Secrets and production access

1. Secrets live in the Instance's root `.env` (git-ignored) until Scaleway Secret Manager is used (backlog), and in [document store] for recovery. Never paste them into chat, email or tickets.
2. Production changes go through reviewed pull requests (`policy-change-management.md`); direct changes on the Instance are emergencies, recorded afterwards.
3. Operator and content roles are granted only from the command line as schema owner and are audited (`policy-access-control.md`).

## 6. Licensed content

Use third-party sources only as their licence allows: no copying of library files outside the platform, no sharing downloads outside our team, no bulk export. Takedowns follow `policy-content-sourcing.md` §6.

## 7. Monitoring

Platform access, operator and content actions are recorded in the audit log, which the security lead may review. Vendor consoles keep their own access logs. No monitoring of personal communications is carried out. [Counsel: confirm the wording and any notice required under Spanish law before an employee or contractor signs.]

## 8. Reporting and breaches of this policy

Report a suspected security incident, lost device, leaked secret or misdirected client data to [security contact email] within [24] hours, and at once if client data may be involved (`policy-incident-response.md`). Breaches of this policy may lead to removal of access and, for employees and contractors, to the measures in their contract.

## 9. Acknowledgement

I have read this policy and will follow it.

| Name | Role | Date | Signature |
| --- | --- | --- | --- |
| [ ] | [ ] | [ ] | [ ] |

Signed copies are kept in [document store].

## 10. Review and approval

Reviewed once a year and when a new kind of access or tool is introduced. Next review: [date].

Approved by: [security lead name], for Estefania Simon-Sasyk y Otro CB, date [date].
