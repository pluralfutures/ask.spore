// P2A-L2: renders the three legal texts from design/compliance/*.md into the static pages
// under public/legal/ that Caddy serves at /legal/privacy, /legal/ai and /legal/terms.
//
//   node scripts/render-legal.mjs           write the pages (drafts allowed; the route stays
//                                           unpublished until ASKSPORE_LEGAL=published)
//   node scripts/render-legal.mjs --check   exit 1 if a page is out of date with its source
//   node scripts/render-legal.mjs --final   also refuse a source that still has a placeholder
//                                           or a DRAFT marker, or a privacy notice whose
//                                           version differs from the consent notice the gate
//                                           shows (run before publishing)
//
// The text is what follows the first "---" line of each source (the notice itself, not the
// owner's front matter). Only the markdown the three sources use is supported: headings,
// paragraphs, bullet and numbered lists, tables, bold, italic, code and links.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { format, resolveConfig } from "prettier";

const here = dirname(fileURLToPath(import.meta.url));
const SOURCE_DIR = join(here, "../../../design/compliance");
const OUT_DIR = join(here, "../public/legal");

export const DOCUMENTS = [
  { slug: "privacy", source: "privacy-notice.md", title: "Privacy notice" },
  { slug: "ai", source: "ai-transparency-note.md", title: "AI transparency note" },
  { slug: "terms", source: "terms-of-use.md", title: "Terms of Use" },
];

const escapeHtml = (text) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function inline(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  // Only https:, mailto: and site-relative (/legal/...) links; anything else stays as text.
  html = html.replace(
    /\[([^\]]+)\]\(((?:https:\/\/|mailto:|\/legal)[^)\s]*)\)/g,
    '<a href="$2">$1</a>',
  );
  return html;
}

const isTableRow = (line) => /^\|.*\|\s*$/.test(line);
const isDivider = (line) => /^\|(\s*:?-+:?\s*\|)+\s*$/.test(line);
const cells = (line) =>
  line
    .trim()
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim());

export function body(markdown) {
  const lines = markdown.split("\n");
  const html = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
    } else if (/^(#{2,3}) /.test(line)) {
      const level = line.match(/^#+/)[0].length;
      html.push(`<h${level}>${inline(line.replace(/^#+ /, ""))}</h${level}>`);
      index += 1;
    } else if (isTableRow(line) && isDivider(lines[index + 1] ?? "")) {
      const head = cells(line);
      index += 2;
      const rows = [];
      while (index < lines.length && isTableRow(lines[index])) rows.push(cells(lines[index++]));
      const headerEmpty = head.every((cell) => !cell);
      html.push("<table>");
      if (!headerEmpty) {
        html.push(`<thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead>`);
      }
      html.push(
        `<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody>`,
      );
      html.push("</table>");
    } else if (/^- /.test(line) || /^\d+\. /.test(line)) {
      const ordered = /^\d+\. /.test(line);
      const marker = ordered ? /^\d+\. / : /^- /;
      const items = [];
      while (index < lines.length && marker.test(lines[index])) {
        items.push(lines[index].replace(marker, ""));
        index += 1;
      }
      const tag = ordered ? "ol" : "ul";
      html.push(`<${tag}>${items.map((item) => `<li>${inline(item)}</li>`).join("")}</${tag}>`);
    } else if (/^---+\s*$/.test(line)) {
      html.push("<hr />");
      index += 1;
    } else {
      const paragraph = [];
      while (
        index < lines.length &&
        lines[index].trim() &&
        !/^(#{2,3} |- |\d+\. |\|)/.test(lines[index])
      ) {
        paragraph.push(lines[index++].trim());
      }
      html.push(`<p>${inline(paragraph.join(" "))}</p>`);
    }
  }
  return html.join("\n");
}

export function noticeText(markdown) {
  const lines = markdown.split("\n");
  const marker = lines.findIndex((line) => /^Plain text below the line/.test(line));
  if (marker < 0) throw new Error("no 'Plain text below the line' marker");
  const rule = lines.findIndex((line, i) => i > marker && /^---\s*$/.test(line));
  if (rule < 0) throw new Error("no rule after the marker");
  return lines.slice(rule + 1).join("\n");
}

// A placeholder is a bracketed phrase that is not a link; a DRAFT marker is the owner's.
export function leftovers(text) {
  const found = [];
  for (const match of text.matchAll(/\[([^\]]+)\](?!\()/g)) found.push(match[0]);
  if (/DRAFT/.test(text)) found.push("DRAFT");
  return found;
}

// "Version 3, ..." in the notice text; the token after "Version".
export function versionOf(text) {
  return /^Version\s+(\S+?),/m.exec(text)?.[1] ?? null;
}

// The version of the use and privacy notice the gate shows (config/models.toml [consent]).
export function consentVersionLine() {
  const config = readFileSync(join(here, "../../../config/models.toml"), "utf8");
  const active = /^\[consent\][^[]*?^version\s*=\s*"([^"]+)"/ms.exec(config)?.[1];
  if (!active) throw new Error("no [consent] version in config/models.toml");
  const notice = readFileSync(join(here, `../../../config/consent/${active}.md`), "utf8");
  return { file: `${active}.md`, version: versionOf(notice) };
}

async function page({ title }, text) {
  const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="robots" content="index, follow" />
    <title>${escapeHtml(title)} · SporeBot</title>
    <link rel="stylesheet" href="/public-page.css" />
  </head>
  <body>
    <!-- P2A-L2. Generated by scripts/render-legal.mjs from design/compliance; edit the source, not this file. Static, outside the app: no script, no API call, no sign-in. -->
    <main>
      <h1>${escapeHtml(title)}</h1>
${body(text)}
      <footer><a href="/legal">Legal</a></footer>
    </main>
  </body>
</html>
`;
  // The project's own prettier settings, so `pnpm lint` finds the pages already formatted.
  const config = (await resolveConfig(join(OUT_DIR, "x.html"))) ?? {};
  return format(html, { ...config, parser: "html" });
}

export async function render() {
  const pages = new Map();
  for (const doc of DOCUMENTS) {
    const text = noticeText(readFileSync(join(SOURCE_DIR, doc.source), "utf8"));
    pages.set(doc, { text, html: await page(doc, text) });
  }
  return pages;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const args = new Set(process.argv.slice(2));
  const pages = await render();
  let failed = false;
  for (const [doc, { text, html }] of pages) {
    const target = join(OUT_DIR, `${doc.slug}.html`);
    if (args.has("--final")) {
      if (doc.slug === "privacy") {
        const consent = consentVersionLine();
        const published = versionOf(text);
        if (published !== consent.version) {
          console.error(
            `${doc.source}: version ${published} differs from the consent notice ${consent.file} (version ${consent.version})`,
          );
          failed = true;
        }
      }
      const left = leftovers(text);
      if (left.length) {
        console.error(`${doc.source}: not final: ${[...new Set(left)].join(", ")}`);
        failed = true;
      }
    }
    if (args.has("--check")) {
      if (!existsSync(target) || readFileSync(target, "utf8") !== html) {
        console.error(`${target} is out of date; run node scripts/render-legal.mjs`);
        failed = true;
      }
    } else {
      writeFileSync(target, html);
    }
  }
  process.exit(failed ? 1 : 0);
}
