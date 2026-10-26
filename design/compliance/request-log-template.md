# Request Log — Template

**DRAFT for owner review, Oct 22, 2026**

| | |
| --- | --- |
| Status | **DRAFT** (template) |
| Date | Oct 22, 2026 |
| Author | Drafted for owner review (evidence template for `policy-content-sourcing.md` §6 and the privacy notice) |
| Placeholders | [document store] |
| To finalise, the owner must | (1) create the live log in [document store] from the columns below (a spreadsheet is enough); (2) never keep the live log in the repository: it holds requesters' names and contact details; (3) review it quarterly (`policy-content-sourcing.md` §7). |

---

One row per request: takedowns, data-subject requests, third-party notices, clients' withdrawal requests and security reports. This file holds only the template; the live log with personal data stays in [document store], retained 3 years after each request is closed (records of processing C6).

## Columns

| Column | Content |
| --- | --- |
| Request ID | `REQ-YYYY-NNN` |
| Received | Date and channel (security@myceliumgastronomy.com, privacyanddata@myceliumgastronomy.com, letter) |
| Type | Publisher takedown · Licence breach found by us · Objection or erasure (platform content) · Access request (platform content) · Client withdrawal (client-supplied file) · Third-party notice (client-supplied file) · Request from a person named in a client-supplied file · Client request to drop a platform source · Security report |
| Requester | Name and contact (live log only) |
| Notice valid? | For third-party notices: file identified, right explained, contact given (yes / missing: …) |
| Sources concerned | Source IDs from the register (no titles needed) |
| Scope | All tenants · one tenant ([tenant slug]) · not applicable |
| Due date | Computed from the window in `policy-content-sourcing.md` §6.2 |
| Action | Withdrawn · suspended · redacted copy ingested · forwarded to client · refused · no action, with the reason |
| Statement of reasons sent | Date (client-supplied files) |
| Requester answered | Date and summary of the decision |
| Closed | Date |
| Handled by | Name |
| Audit reference | `takedown_reference` or audit event ID |

## Example row (synthetic)

| Request ID | Received | Type | Requester | Notice valid? | Sources | Scope | Due | Action | Statement sent | Answered | Closed | By | Audit ref |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| REQ-2026-001 | 2026-11-02, takedown mailbox | Publisher takedown | (in live log) | n/a | 1234 | One tenant (`example-tenant`) | 2026-11-16 | Withdrawn for that tenant; excerpts blanked | n/a | 2026-11-05 | 2026-11-05 | [name] | TD-2026-001 |
