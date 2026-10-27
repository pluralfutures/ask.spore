# Trust Page — Draft Text

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 19, 2026 |
| Author | Drafted for owner review (spec item P1a-15) |
| Revision | Oct 22, 2026, **DRAFT**: "Your own documents" section and the first paragraph, for clients that supply documents (P1b-19 step 1, architecture §15); publish only once P1b-19 step 2 is built |
| Publishing (P2A-11, Oct 25, 2026) | Caddy has a `/trust` route that answers 404 until the deploy-time flag `ASKSPORE_TRUST_PAGE=published` is set in `infra/.env`. To publish: render the final text as `apps/web/public/trust.html` (static, no inline script or style, like `security-disclosure.html`), deploy, set the flag, `restart caddy`. Until paperwork item 4 clears, neither is done |
| To finalise, the owner must | (1) fill in the contact addresses and legal entity; (2) replace the "External models" location sentence with the outcome of the TIA verification (findings C32); (3) remove the sentence on deletion timing that does not match the build at publication (see the note under "Retention"); (4) the sub-processor list is linked at `/legal/sub-processors`: publish it first (`sub-processors.md`, Publishing); (5) have counsel check it against the DPA and privacy notice. Plain text below the line is the page. |

---

## How we handle your data

SporeBot is a research assistant. It answers questions from a curated library of published reports, public websites and our own analysis, and shows the sources for every answer. You do not upload documents to it, unless your contract provides for supplying your own documents (see "Your own documents").

### Where your data lives

Everything we store is hosted by Scaleway in Paris, France: the application, the database with your conversations, the search index, the files you can download, our logs and our backups.

### Which models answer your questions

By default, questions are answered by models run by Scaleway in the European Union (DeepSeek V4.1 Flash and Qwen 3.8 27B). Nothing leaves the EU.

### When data leaves the EU

Only if your organisation has asked for **external models** (Claude Opus 5.5 and GPT-6.1 Sol), signed for them, and we have switched them on for you. Even then, only conversations where a user picks one of those models are affected, and the model picker says that these models are served outside the EU.

For those conversations, the question, the recent turns of the conversation, your workspace's instructions and excerpts from the library are sent through OpenRouter's EU endpoint to the model's provider: Amazon Web Services for Claude, Microsoft Azure for GPT. These providers may process the request outside the EU, including EEA, UK, and Switzerland. We send no names, email addresses or account identifiers with the request, require zero data retention from every provider on every request, and forbid them to use it for training. The transfer is covered by the EU Standard Contractual Clauses.

Your organisation's monthly spend on external models is capped.

### How long we keep things

- Conversations: 30 days at most. Your administrator can shorten this to as little as one day. No setting keeps them longer.
- Accounts: while your organisation uses the service.
- Security and audit records (who signed in, who downloaded what, when a question was asked; never the question or answer text): 12 months.
- Model providers: nothing, under zero-data-retention terms, except where a provider must keep a request by law or to investigate abuse.

Conversations past their retention disappear from the service but are deleted from the database during monthly routine maintenance.

### Signing in

You sign in with a link we email to you. The link works once, for 15 minutes, and only after you press the button on the page it opens, so email security scanners that open links cannot use it. Administrators may also enable SSO with Google and Microsoft Entra. Sign-in emails are sent by Scaleway in Paris.

### Downloads

You can see the list of files behind each workspace. You can download a file only where its licence allows us to share it, which today mostly means our own analyses. For other files we link to the publisher. Each download link works once, for one minute, and the number of downloads per person per day is limited.

### Your own documents

Some organisations send us their own documents to be searched in their workspaces. Those documents are searchable and downloadable only by that organisation's users, stored in Paris, used only to answer that organisation's questions, never used for training, withdrawn on request and deleted at the end of the contract with a certificate. The organisation decides what it sends and is responsible for its rights in it.

### Reporting content

*DRAFT, Oct 22, 2026 (from `policy-content-sourcing.md` §6).* If you believe content in our library infringes your rights, or you are named in it and want it removed or corrected, write to security@myceliumgastronomy.com. Please identify the document or page, explain the right or concern, and give a way to reach you. We act on publisher takedowns within 10 working days and on personal-data requests within 30 days. For documents a customer supplied, we may suspend the document at once and pass personal-data requests to that customer, who decides on them.

### What we never do

- Train or fine-tune any model on your questions or conversations.
- Write your questions, answers or prompts into our logs. Logs hold technical metadata only.
- Show one organisation's questions or answers to another.
- Send names, email addresses or account identifiers to a model.
- Let the model browse, run tools or change anything. It reads the excerpts we give it and writes an answer.
- Sell your data.

### Sub-processors

The companies that process your data on our behalf are listed at [Sub-processors](/legal/sub-processors). We give customers [30] days' notice before adding one.

### Contact

- Privacy and data protection requests: privacyanddata@myceliumgastronomy.com
- Security reports: security@myceliumgastronomy.com
- Removal of content or personal data from our library (publishers and individuals): privacyanddata@myceliumgastronomy.com

Mycelium Gastronomy Network (trade name) for Estefania Simon-Sasyk y Otro CB, Hermanos Otamendi kalea, 11, 20014 San Sebastián, Gipuzkoa, Spain

Last updated: 26 October 2026
