# Incident Response Policy — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [security lead name], [security contact email], [lead supervisory authority], [48] (DPA notification window, hours), [document store], [date] |
| To finalise, the owner must | (1) confirm the client notification window with counsel (the DPA draft says [48] hours); (2) name the lead supervisory authority; (3) schedule the first tabletop; (4) approve and sign. |

---

## 1. Purpose and scope

How we detect, handle, notify and learn from security incidents and personal data breaches affecting the platform, client data, the corpus or vendors. The step-by-step procedure, contact list and notification template are in `incident-runbook.md`.

## 2. Rules

1. **Anyone who suspects an incident reports it at once** to [security contact email]. External reports arrive at the same address.
2. **Severity** is set at triage: Sev 1 (client data exposed or likely exposed, e.g. a cross-tenant read; platform down), Sev 2 (control failure without known exposure, e.g. a body in a log line), Sev 3 (anything else).
3. **Contain first, preserve evidence.** The audit log is append-only; do not delete logs or rows during an investigation.
4. **Client notification.** As processor, we notify the affected client without undue delay and within **[48] hours** of becoming aware of a breach of their data (client DPA clause 9.1), with the Art. 33(3) facts known so far.
5. **Authority notification.** For data where we are controller (corpus personal data, our own logs), we notify [lead supervisory authority] within 72 hours unless the breach is unlikely to result in a risk (Art. 33), and the people affected where the risk is high (Art. 34).
6. **Every incident is recorded** in the incident log, including those not notified, with the reasoning (Art. 33(5)).
7. **Vendor incidents** reported to us by a sub-processor are handled as our own.
8. **Post-incident review** within 10 working days for Sev 1 and 2; actions go to `risk-register.md`.
9. **A tabletop exercise** once a year.
10. Incident records never contain question or answer text; they cite IDs and metadata.

## 3. Roles

The owner is incident lead, communications lead and decision-maker. Counsel advises on notification. There is no on-call rota; detection depends on the owner, client reports and vendor notices (`risk-register.md` R-25).

## 4. Controls and evidence

| Control | Evidence the system already produces | Status |
| --- | --- | --- |
| Audit trail for investigation (CC7.2, CC7.3) | Append-only `audit_events` (trigger rejects UPDATE and DELETE): `auth.login`, `chat.query` (metadata and cited chunk IDs, no text), `download`, `operator.*`, `tenant_admin.*` | Built |
| Metadata-only logs, error lines with request ID (CC7.2) | `api.error` line from ErrorBoundary (e0435c1) | Built |
| Detection of anomalies and bulk extraction (CC7.2) | — | Not built (open; monitoring stack in backlog) |
| Runbook and template (CC7.4) | `incident-runbook.md` | Drafted |
| Breach notification window (CC7.4, Art. 33) | Client DPA clause 9.1 | Drafted |
| Incident log (CC7.5) | [document store]/incidents/ | Not started |
| Tabletop (CC7.4) | Minutes | Not held |

## 5. Review and approval

Reviewed once a year and after every Sev 1. Next review: [date].

Approved by: [security lead name], for Estefania Simon-Sasyk y Otro CB, date [date].
