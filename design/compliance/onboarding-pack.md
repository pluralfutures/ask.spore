# Client Onboarding Pack — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [Client], [sending domain], [sender address], [support email], [privacy contact email], [security contact email], [client IT contact], [Entra redirect URI], [Google redirect URI], [OIDC redirect URI], [SAML ACS URL], [SAML entity ID], [secret transfer method], [recipient first name], [inviter name], [workspace name], [notice version], [notice summary], [notice path], [date] |
| To finalise, the owner must | (1) fill in the placeholders, using `askspore.myceliumgastronomy.com` for askspore.myceliumgastronomy.com unless a client-facing host replaces it; (2) choose the [secret transfer method] for SSO client secrets and SAML keys (section 1.5); (3) check the email templates in section 2 against the copy that P1b-11 and the Authentik template ship with, and keep the two in step; (4) remove the "not yet built" notes once the matching spec items pass their tests; (5) run the live scanner test (P1b-13(a)) with [Client]'s IT contact before the first `customculinary.com` user is invited, and record the result in the Phase 1b findings; (6) have counsel check section 2.3 (consent notice) against `privacy-notice.md` and `terms-of-service.md`. |

Section 1 goes to [Client]'s IT contact. Sections 2 and 3 are templates and guidance used by us and by [Client]'s tenant administrator. Section 4 goes to the tenant administrator.

---

## 1. IT and SSO setup sheet

For [client IT contact]. It lists what SporeBot needs from your mail and identity setup, and what it does not need.

### 1.1 What SporeBot is, in one paragraph

SporeBot is a web research assistant run by Estefania Simon-Sasyk y Otro CB. Your users sign in in a browser at `https://askspore.myceliumgastronomy.com`. Nothing is installed on your devices, and your users upload no documents. Everything we store is hosted by Scaleway in Paris, France. See `security-questionnaire.md` for the details your security team may ask for.

### 1.2 What to allow

| Item | Value | Why |
| --- | --- | --- |
| Web address | `https://askspore.myceliumgastronomy.com` (port 443 only; HTTP redirects to HTTPS) | The app and its sign-in page |
| Email sending domain | `[sending domain]`, sender `[sender address]` | Sign-in links and platform mail |
| Email service | Scaleway Transactional Email, region fr-par (Paris). The domain is authenticated with SPF, DKIM and DMARC | So your mail gateway can recognise our mail as genuine |
| Backup email service | Mailgun, EU region. **Not active.** We would tell you before switching to it | Listed so you are not surprised; nothing is sent through it today |

Nothing else is needed: no browser extension, no VPN, no inbound connection to your network.

### 1.3 Sign-in links and mail security scanners

Users can sign in with a single-use link sent by email. Many mail gateways (for example Microsoft Defender Safe Links, Mimecast, Proofpoint) open every link in a message before the user sees it. Our links are built so that this does no harm:

- The link opens a landing page. Opening it does **not** sign anyone in. The user has to press the button on that page, and only that press uses the link.
- The secret part of the link sits after a `#`, which browsers and scanners do not send to our server when they fetch the page.
- A link works **once**, for **15 minutes**, and **only in the browser where the user asked for it**. If a user requests the link in one browser and opens the email in another, the link is refused; they should open it in the same browser window, or request a new one there.
- We send at most 5 links per user within a link's lifetime. Further requests send nothing.
- The sign-in page never tells anyone whether an address has an account.

What we ask of your IT team:

1. If your gateway rewrites links, either allow `askspore.myceliumgastronomy.com` to pass unrewritten, or confirm that the rewritten link still lands on our page with everything after the `#` intact. Some rewriters drop the fragment, and then the link cannot work.
2. Allow mail from `[sending domain]` so sign-in links are not quarantined. They expire after 15 minutes, so a delayed message is a useless one.
3. Tell us which mail client and which link scanner your users have. Before we invite the first of your users, we test a real sign-in end to end with your setup (spec item P1b-13(a)). We record the result; no message content is kept.

Once your SSO connection is live, the operator switches sign-in links off for your organisation, so that only single sign-on works (from Phase 1b, P1b-06). Links stay on only if your organisation asks for them and the operator enables them for you (owner decision, Oct 21, 2026).

### 1.4 Single sign-on (from Phase 1b)

Single sign-on is configured by our operator together with you; there is no self-service screen (that is Phase 3). It is built in Phase 1b (spec item P1b-07) in this order: Microsoft Entra ID, Google Workspace, then generic OIDC and SAML 2.0. Until your connection is live, your users sign in with emailed links (section 1.3).

Whichever option you choose:

- **Verified domains.** You tell us the email domains your users sign in with (for example `customculinary.com`). One domain belongs to one organisation on SporeBot. We check that you control it before we register it.
- **Which organisation a user belongs to** is decided by us, from the SSO connection the user arrives through. It is never taken from a claim your identity provider sends. A user of one organisation cannot land in another's (tested).
- **Just-in-time accounts.** If you want, users who sign in through your SSO get an account on first sign-in, but only for an address on a verified domain. If you switch this off, only invited users can sign in.
- **What we receive from your identity provider:** email address, name if sent, and optionally a group membership to mark administrators. We do not need, and do not ask for, any directory read access.

| Option | What we need from you | What we give you |
| --- | --- | --- |
| Microsoft Entra ID (OIDC) | Your Entra **tenant ID** (we pin it in the issuer, so only your tenant's tokens are accepted); an app registration with redirect URI `[Entra redirect URI]`; its **client ID** and a **client secret**; optionally the **group** whose members should be administrators in SporeBot | The redirect URI; the claims we read (`email`, `name`, optional `groups`) |
| Google Workspace (OIDC) | An OAuth client with redirect URI `[Google redirect URI]`; client ID and secret; your Workspace domain. We check the `hd` (hosted domain) claim against your verified domains and refuse a mismatch | The redirect URI |
| Generic OIDC | Issuer URL (with discovery), client ID and secret, redirect URI `[OIDC redirect URI]` | The redirect URI and the claims we read |
| SAML 2.0 | Your IdP metadata (XML file or URL); email as NameID or an attribute | Our ACS URL `[SAML ACS URL]` and entity ID `[SAML entity ID]` |

### 1.5 How to send us secrets

Send client secrets and SAML keys by [secret transfer method], never by ordinary email or in a ticket. They are stored only in our identity service (Authentik, self-hosted in Paris), not in the application database. Your tenant administrator can see the configured connection read-only in SporeBot; nobody, including us, can display the secret again after it is entered. Rotate the secret on your side whenever you need to and send us the new one the same way.

### 1.6 Administrator second factor (from Phase 1b)

From Phase 1b (spec item P1b-08), SporeBot requires a second factor for your tenant administrators. See section 3. If your users sign in through your SSO, your own MFA policy applies to them as usual.

### 1.7 Contacts

- Support and setup: [support email]
- Security reports: [security contact email]
- Privacy and data protection: [privacy contact email]

---

## 2. Email templates

Rules for every template below:

- Sent from `[sender address]` over Scaleway Transactional Email (fr-par). Open and click tracking are off, so links are never rewritten through a tracking redirect.
- The email names only the recipient's own details (their address or first name, and their own organisation's workspace where needed). It never names another user, and never includes a question, an answer or a document.
- The service does not log recipient addresses, subjects or bodies (P1b-11 test).
- Plain text below; the HTML version carries the same words.

**What is built today (Oct 21, 2026).** Only the sign-in link email (2.2) is sent, by Authentik. Invitations send no email in Phase 1a: an invited user goes to `https://askspore.myceliumgastronomy.com` and requests a link there. The platform's own mail (invitations, notices) is sent from Phase 1b (spec item P1b-11).

### 2.1 Invitation (from Phase 1b, P1b-11)

Subject: You have been invited to SporeBot

> Hello [recipient first name],
>
> [inviter name] has invited you to SporeBot, the research assistant your organisation uses.
>
> To sign in, go to https://askspore.myceliumgastronomy.com and enter this email address. We will send you a sign-in link. Open it in the same browser where you asked for it, and press the button on the page it opens. [*If the organisation uses SSO:* "Choose 'Sign in with your organisation' and use your usual work account."]
>
> Before your first conversation you will be asked to read and accept the use and privacy notice.
>
> If you were not expecting this invitation, you can ignore this email.
>
> SporeBot · Estefania Simon-Sasyk y Otro CB · [support email]

The invitation carries no sign-in link, on purpose: a link only works in the browser that requested it.

### 2.2 Sign-in link (built, Authentik template `infra/authentik/templates/ask-spore-sign-in.html`)

Subject: Sign in to ask.spore

> Use this link to sign in to ask.spore. It works once, in the browser where you asked for it, and expires in 15 minutes.
>
> [Sign in to ask.spore] → `https://askspore.myceliumgastronomy.com/auth/finish#token=…`
>
> If you did not ask to sign in, ignore this email.

Notes: the token sits in the fragment (after `#`), never in a query string. The product name is hard-coded as "ask.spore" in the subject and body today, but the client-facing name is SporeBot (owner, Oct 21, 2026). Before the first client user is invited, the template and the Authentik email stage's subject change together to "Sign in to SporeBot" (an infra change, not made in this document set).

### 2.3 Updated use and privacy notice (from Phase 1b, P1b-10 and P1b-11)

Subject: We have updated the SporeBot use and privacy notice

> Hello [recipient first name],
>
> We have updated the notice that explains how SporeBot may be used and how we handle your data (version [notice version], effective [date]).
>
> What changed, in short: [notice summary]
>
> The next time you sign in, you will be asked to read and accept the new version before you can continue. You can read it now at https://askspore.myceliumgastronomy.com/[notice path].
>
> Questions: [privacy contact email]
>
> SporeBot · Estefania Simon-Sasyk y Otro CB

The acceptance itself is recorded in the app at sign-in (user, notice version, time), not by replying to this email.

### 2.4 Administrator second-factor enrolment (from Phase 1b, P1b-08 and P1b-11)

Subject: Set up a second factor for your SporeBot administrator account

> Hello [recipient first name],
>
> You are an administrator of your organisation's SporeBot account. Administrators must use a second factor when they sign in.
>
> The next time you sign in, you will be asked to set one up: an authenticator app on your phone, or a security key or passkey. It takes about two minutes. Keep the recovery codes you are shown somewhere safe.
>
> We will never ask you for a code, a recovery code or a sign-in link by email, phone or chat.
>
> Help: [support email]
>
> SporeBot · Estefania Simon-Sasyk y Otro CB

---

## 3. Administrator MFA guidance (from Phase 1b, P1b-08)

For tenant administrators. Until P1b-08 ships, administrators sign in with an emailed link only; the second factor below is not yet enforced.

**What is required.** A second factor every time a tenant administrator signs in. It is enforced by our identity service (Authentik), through a check bound to the administrator group. Users who are not administrators are not asked for one by SporeBot; your own SSO policy may still ask them.

**Which factor to choose.**

| Factor | Recommendation |
| --- | --- |
| Security key or passkey (WebAuthn) | Best. Resistant to phishing. Register two if you can (one kept as a spare) |
| Authenticator app (TOTP: for example Microsoft Authenticator, Google Authenticator, 1Password) | Good. Six-digit code that changes every 30 seconds |
| SMS or email codes | Not offered |

**Recovery.**

- Save the recovery codes shown at enrolment in your password manager, not in email or on the same phone.
- If you lose your factor and your codes, ask another administrator of your organisation to contact [support email], or contact us from your work address. We confirm the request with your organisation's named contact before we reset anything, and the reset is audited.
- After a reset, enrol a new factor at your next sign-in.

**What we will never do.**

- Ask you for a sign-in link, a one-time code or a recovery code, by any channel.
- Ask you to install software or browser extensions.
- Send a sign-in link you did not ask for. If you receive one, ignore it, and tell [security contact email] if it keeps happening.

**When you leave your role.** Ask another administrator to remove your administrator role, or tell us. Remove your security key or authenticator entry afterwards.

---

## 4. First-week checklist for the tenant administrator

| # | Step | Notes |
| --- | --- | --- |
| 1 | Confirm your organisation's email domains with us | Only addresses on verified domains can be invited. One domain belongs to one organisation |
| 2 | Sign in for the first time | Request a link at `https://askspore.myceliumgastronomy.com`, open it in the same browser, press the button. From Phase 1b: accept the use and privacy notice (P1b-10) and set up your second factor (section 3) |
| 3 | Invite your users | Admin page → Users → Invite. In Phase 1a no invitation email is sent: tell each person to go to `https://askspore.myceliumgastronomy.com` and request a link. From Phase 1b the platform sends the invitation (template 2.1). Inviting an address that already has an account anywhere on SporeBot is refused |
| 4 | Set the history retention | Conversations are kept for at most 30 days. You can shorten this to between 1 and 30 days. No setting allows more. A "no history" setting (0 days) comes with P1b-14. In Phase 1a an expired conversation disappears from the app at once; it is deleted from the database by the purge job from Phase 1b (P1b-14) |
| 5 | Review each workspace's defaults | Default answer mode and default model, among those our operator enabled for you |
| 6 | Write the workspace instructions, if you want them | See the guidance below |
| 7 | Check the file list of each workspace | Shows the sources each workspace searches. Files can be downloaded only where the source's licence allows; others link to the publisher. Each person can download at most 50 files a day |
| 8 | Deactivate users who leave | Admin page → Users. Deactivation takes effect at their next request and is recorded in the audit log. See `offboarding-pack.md` for the notice template |
| 9 | Tell us about anything odd | Unexpected sign-in emails, answers that seem to show another organisation's material, or anything else: [security contact email] |

**Writing workspace instructions.** Each workspace has an "additional instructions" box. Its text is added, in a separate marked section, to the instructions the model receives with every question in that workspace. It can shape tone, focus and format. It cannot switch off citations, the rule that answers come from your sources, or the platform's other rules.

- Do not put personal data in it: no names of staff, customers or other people, no email addresses.
- Avoid your organisation's own name and your staff's names. They are allowed, because the text is yours, but our operator is notified when the text matches your organisation's name, domains or user names, so that we can check nothing was added by mistake. Nothing is shown to your users and nothing is removed.
- Keep it short (at most 2,000 characters). Every saved version is kept and audited.
- Do not paste confidential material into it; it is sent to the model with every question.

**Models.** Your users can choose, per conversation, among the models our operator enabled for you. By default these are models run by Scaleway in Paris. **External models** (Claude Opus 5.5 and GPT-6.1 Sol, served outside the EU through OpenRouter) are off. They are switched on only after your organisation signs the acceptance in Annex 4 of the data processing agreement, with a monthly spend cap, and after we have completed our own checks. When they are on, the model picker tells users that these models are served outside the EU.

**Where to look things up.** How we handle data: the trust page and `privacy-notice.md`. Terms: `terms-of-service.md`. How answers are produced and their limits: `ai-transparency-note.md`.
