import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import {
  canEdit,
  canReview,
  emptyProposal,
  errorMessage,
  historyLine,
  needsLicenceLetter,
  pageReason,
  parsePatterns,
  proposalForm,
  timerText,
  timerTone,
} from "./content";

const fields = {
  ...emptyProposal,
  title: "Synthetic Outlook 2026",
  publisher: "Synthetic Institute",
  licenceBasis: "publisher-terms",
  tags: ["sample-reports"],
};
const pdf = new File([new Uint8Array([37, 80, 68, 70])], "synthetic.pdf");

describe("roles", () => {
  it("editors propose, reviewers review, one person may be both", () => {
    expect(canEdit(["content_editor"])).toBe(true);
    expect(canReview(["content_editor"])).toBe(false);
    expect(canReview(["content_editor", "content_reviewer"])).toBe(true);
  });
});

describe("takedown timer", () => {
  it("counts working days and flags overdue requests", () => {
    expect(timerText(10)).toBe("10 working days left");
    expect(timerText(1)).toBe("1 working day left");
    expect(timerText(0)).toBe("due today");
    expect(timerText(-1)).toBe("1 working day overdue");
    expect(timerText(-3)).toBe("3 working days overdue");
    expect([timerTone(5), timerTone(2), timerTone(-1)]).toEqual(["ok", "due", "overdue"]);
  });
});

describe("proposal form", () => {
  it("needs a file or a URL, not both", () => {
    expect(proposalForm(fields, null, null)).toHaveProperty("error");
    expect(proposalForm({ ...fields, url: "https://example.org/x" }, pdf, null)).toHaveProperty(
      "error",
    );
    const result = proposalForm({ ...fields, url: "https://example.org/x" }, null, null);
    expect("form" in result && result.form.get("url")).toBe("https://example.org/x");
  });

  it("requires a letter for a downloadable third-party file, not for own work", () => {
    const downloadable = { ...fields, downloadable: true };
    expect(needsLicenceLetter(downloadable, false)).toBe(true);
    expect(proposalForm(downloadable, pdf, null)).toEqual({
      error: expect.stringContaining("permission letter"),
    });
    const letter = new File(["synthetic"], "letter.pdf");
    const withLetter = proposalForm(downloadable, pdf, letter);
    expect("form" in withLetter && withLetter.form.get("licence_file")).toBeInstanceOf(File);
    expect(needsLicenceLetter({ ...downloadable, licenceBasis: "own-work" }, false)).toBe(false);
    expect(needsLicenceLetter({ ...downloadable, licenceBasis: "open-licence" }, false)).toBe(
      false,
    );
  });

  it("sends every tag and the flag as form fields", () => {
    const result = proposalForm(
      { ...fields, tags: ["a", "b"], publishedOn: "2026-03-01" },
      pdf,
      null,
    );
    if (!("form" in result)) throw new Error(result.error);
    expect(result.form.getAll("tags")).toEqual(["a", "b"]);
    expect(result.form.get("downloadable")).toBe("false");
    expect(result.form.get("published_on")).toBe("2026-03-01");
    expect(result.form.get("canonical_url")).toBeNull();
  });

  it("refuses missing metadata and tags", () => {
    expect(proposalForm({ ...fields, title: " " }, pdf, null)).toHaveProperty("error");
    expect(proposalForm({ ...fields, tags: [] }, pdf, null)).toHaveProperty("error");
  });
});

describe("labels", () => {
  it("explains blocked pages and history entries", () => {
    expect(pageReason("special_category", "political_person")).toBe(
      "special category: political person",
    );
    expect(pageReason("http_404", null)).toBe("gone (404)");
    expect(pageReason(null, null)).toBe("");
    expect(
      historyLine({
        event: "source.approved",
        actor: null,
        before: "proposed",
        after: "approved",
        method: "site_crawl",
      }),
    ).toBe("approved (proposed → approved) · site crawl");
    expect(parsePatterns(" /a/*\n\n/b \n")).toEqual(["/a/*", "/b"]);
  });

  it("turns API codes into sentences", () => {
    expect(errorMessage(new ApiError(422, "replacement_choice_required"))).toContain(
      "replaces it, or keep both",
    );
    expect(errorMessage(new ApiError(403, "forbidden"))).toContain("role");
    expect(errorMessage(new ApiError(409, "something_else"))).toBe("Refused (something_else).");
    expect(errorMessage(null)).toBeNull();
  });
});
