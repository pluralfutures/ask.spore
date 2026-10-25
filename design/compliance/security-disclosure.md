# Responsible Disclosure Page and security.txt — Draft Text

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 25, 2026 |
| Author | Drafted for owner review (spec item P2A-11) |
| Published as | `apps/web/public/.well-known/security.txt` (served at `/.well-known/security.txt`) and `apps/web/public/security-disclosure.html` (served at `/security-disclosure`), both by Caddy outside the application, its sign-in and its consent gate (`infra/caddy/Caddyfile`). This document is the source text: change it and both files in the same commit (`apps/api/tests/test_public_files.py` checks that the `security.txt` block below matches the file) |
| Owner decisions, Oct 25, 2026 | Contact `security@myceliumgastronomy.com` in both files, also for takedown requests until a separate mailbox exists; no PGP key at launch (the `Encryption:` line stays a comment, `security.txt` is not signed); the safe-harbour paragraph is kept |
| To finalise, the owner must | (1) have counsel confirm the safe-harbour wording ("Safe harbour" below) under the governing law the terms name; (2) fill in the legal entity (counsel); (3) renew `Expires` before it passes (the test fails once it is past, or more than a year away) |

Questions for the owner are in `design/specs/phase-2a-findings.md`, section 3.

---

## security.txt

RFC 9116. `Expires` is less than a year ahead, as the RFC recommends; renew it with the
yearly policy review. Lines starting with `#` are comments and are published as they are.

```
# security.txt for SporeBot (RFC 9116). Draft: see design/compliance/security-disclosure.md.
Contact: mailto:security@myceliumgastronomy.com
Expires: 2027-10-01T00:00:00Z
Preferred-Languages: en
Policy: https://askspore.myceliumgastronomy.com/security-disclosure
Canonical: https://askspore.myceliumgastronomy.com/.well-known/security.txt
# Encryption: https://askspore.myceliumgastronomy.com/.well-known/pgp-key.txt
```

## Page text

Plain text below is the page (`/security-disclosure`).

### Reporting a security vulnerability

We take the security of SporeBot and of our clients' data seriously. If you believe you have
found a security vulnerability in our service, please tell us. We will work with you to
understand and fix it.

### How to report

Email **security@myceliumgastronomy.com**. Please include:

- what you found and where (the page, the request or the component);
- the steps to reproduce it, and what an attacker could do with it;
- how we can reach you for follow-up questions.

Please write in English.

### What we ask of you

- Test only against accounts you own or have permission to use. Never access, change or
  delete another person's or another organisation's data. If you reach such data by
  accident, stop, do not keep a copy, and tell us in your report.
- Do not run denial-of-service tests, spam, social engineering, or physical tests against
  our staff, offices or hosting providers.
- Do not use automated scanners at a volume that degrades the service for others.
- Give us reasonable time to fix the issue before you disclose it publicly. We suggest 90
  days from your report, or earlier once we confirm a fix.

### What we will do

- Acknowledge your report within [3] working days.
- Tell you whether we can reproduce it and keep you informed of our progress.
- Credit you, if you wish, once the issue is fixed.

We do not offer payment for reports at this time.

### Safe harbour

[*Draft, for counsel:*] If you act in good faith and follow this policy, we will consider
your research authorised, we will not pursue or support legal action against you for it, and
we will not report you to law enforcement. If a third party brings action against you for
research done under this policy, we will make it known that you acted with our
authorisation. This does not authorise you to act against third parties, including our
hosting and model providers, whose own policies apply.

### Out of scope

- Findings that need a compromised device or a man-in-the-middle position on the user's own
  network.
- Missing best-practice headers or settings with no demonstrated impact.
- Reports from automated tools without a working proof of concept.
- Content in our library: to ask for the removal of content or personal data, write to
  security@myceliumgastronomy.com (the security mailbox until a separate takedown address exists).

Mycelium Gastronomy Network (trade name) for Estefania Simon Sasyk u Otro CB, Hermanos Otamendi kalea 11, 20014 Donostia-San Sebastián, Guipúzcoa, Spain

Last updated: 26 October 2026
