import { describe, expect, it } from "vitest";

// UX-04: components use the semantic theme tokens of index.css, never raw palette, size,
// weight or radius classes, so the look changes in one file (UX-05).
const RAW =
  /(?<![\w-])((?:bg|text|border|ring|divide|outline)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}|(?:bg|text|border)-(?:white|black)|text-(?:xs|sm|base|lg|xl|[2-9]xl)|font-(?:thin|light|medium|semibold|bold|extrabold|black)|rounded(?:-(?:xs|sm|md|lg|xl|2xl|3xl|full))?)(?![\w-])/g;

// Every component's source, as text (Vite's raw import; tests are excluded). Vitest's module
// cache keeps this list until the cache is cleared, so a brand-new file is checked on a
// fresh run (as in CI); edits to existing files are checked every run.
const SOURCES = import.meta.glob<string>(["./**/*.tsx", "!./**/*.test.tsx"], {
  query: "?raw",
  import: "default",
  eager: true,
});

describe("theme tokens", () => {
  it("no component uses a raw palette, size, weight or radius class", () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(30);
    const found = Object.entries(SOURCES).flatMap(([file, text]) =>
      [...text.matchAll(RAW)].map((m) => `${file}: ${m[1]}`),
    );
    expect(found).toEqual([]);
  });

  it("catches a raw class", () => {
    expect('className="rounded bg-slate-900 text-sm"'.match(RAW)).toEqual([
      "rounded",
      "bg-slate-900",
      "text-sm",
    ]);
    expect('className="rounded-control bg-primary text-ui"'.match(RAW)).toBeNull();
  });
});
