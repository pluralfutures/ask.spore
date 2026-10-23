import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import { SaveStatus } from "./SaveStatus";

describe("SaveStatus (P1c-08)", () => {
  it("shows nothing before a save", () => {
    expect(renderToString(<SaveStatus isSuccess={false} error={null} />)).toBe("");
  });

  it("confirms a save", () => {
    const html = renderToString(<SaveStatus isSuccess error={null} />);
    expect(html).toContain('role="status"');
    expect(html).toContain("Saved.");
    expect(
      renderToString(<SaveStatus isSuccess error={null} savedText="Tenant created." />),
    ).toContain("Tenant created.");
  });

  it("shows the refusal instead", () => {
    const html = renderToString(
      <SaveStatus isSuccess={false} error={new ApiError(409, "slug_taken")} />,
    );
    expect(html).toContain("That slug is already in use.");
    expect(html).not.toContain("Saved.");
  });
});
