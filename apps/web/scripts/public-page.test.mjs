import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// P2B-02: the static public pages (/legal and its documents, /security-disclosure) look like
// the app. The stylesheet copies the app's theme tokens and font files; these tests fail if
// the copies drift, so the look is still changed in one place (src/index.css).
const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path) => readFileSync(join(WEB, path), "utf8");
const indexCss = read("src/index.css");
const pageCss = read("public/public-page.css");

// "--name: value;" declarations, whitespace-normalised (some span two lines).
function declarations(css) {
  const found = new Map();
  for (const m of css.matchAll(/(--[\w-]+):\s*([^;]+?)\s*(?:\/\*[^*]*\*\/)?;/g)) {
    found.set(m[1], m[2].replace(/\s+/g, " "));
  }
  return found;
}

const PAGES = [
  "public/legal/index.html",
  "public/legal/privacy.html",
  "public/legal/ai.html",
  "public/legal/terms.html",
  "public/security-disclosure.html",
];

describe("public pages follow the app's design (P2B-02)", () => {
  it("copies every theme token it uses from src/index.css with the same value", () => {
    const app = declarations(indexCss);
    const page = declarations(pageCss);
    const tokens = [...page.keys()].filter((name) => app.has(name) || name.startsWith("--color"));
    expect(tokens.length).toBeGreaterThan(15);
    for (const name of tokens) expect(page.get(name), name).toBe(app.get(name));
  });

  it("uses only tokens that exist in the app", () => {
    const app = declarations(indexCss);
    for (const name of declarations(pageCss).keys()) expect(app.has(name), name).toBe(true);
  });

  it("serves the same font files, byte for byte, at stable addresses", () => {
    const urls = [...pageCss.matchAll(/url\("\/fonts\/([\w-]+\.woff2)"\)/g)].map((m) => m[1]);
    expect(urls.length).toBe(7);
    for (const file of urls) {
      const dir = file.startsWith("poppins") ? "poppins" : "lato";
      const source = readFileSync(join(WEB, `src/assets/fonts/${dir}/${file}`));
      expect(readFileSync(join(WEB, `public/fonts/${file}`)).equals(source), file).toBe(true);
    }
    for (const licence of ["OFL-lato.txt", "OFL-poppins.txt"]) {
      expect(readFileSync(join(WEB, `public/fonts/${licence}`)).length).toBeGreaterThan(0);
    }
  });

  it("has no dark scheme, no remote resource and no inline-style dependency", () => {
    expect(pageCss).not.toMatch(/prefers-color-scheme/);
    expect(pageCss).not.toMatch(/url\((?!"\/fonts\/)/);
    expect(pageCss).not.toMatch(/@import/);
  });

  it("gives every page the app's header with the product name, and its footer", () => {
    const part = (html, tag) =>
      new RegExp(`<${tag} class="site-${tag}">[\\s\\S]*?</${tag}>`).exec(html)?.[0];
    const header = part(read(PAGES[0]), "header");
    const footer = part(read(PAGES[0]), "footer");
    expect(header).toContain('<span class="brand-mark">Mycelium</span> SporeBot');
    expect(footer).toContain('<a href="/legal">Legal</a>');
    for (const page of PAGES) {
      const html = read(page);
      expect(part(html, "header"), page).toBe(header);
      expect(part(html, "footer"), page).toBe(footer);
      expect(html, page).toContain('<main id="main">');
      expect(html, page).toContain('<link rel="stylesheet" href="/public-page.css" />');
      expect(html, page).not.toMatch(/<script|style="/i);
    }
  });

  it("wraps every table in a labelled, focusable scroll region", () => {
    const html = read("public/legal/privacy.html");
    const tables = html.match(/<table>/g)?.length ?? 0;
    expect(tables).toBeGreaterThan(0);
    expect(
      html.match(/<div class="table-scroll" role="group" aria-label="Table" tabindex="0">/g),
    ).toHaveLength(tables);
  });
});
