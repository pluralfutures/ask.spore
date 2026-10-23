import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import { errorText } from "./operator";

describe("console refusals (P1c-07)", () => {
  it("explains a taken address instead of a status code", () => {
    expect(errorText(new ApiError(409, "email_taken"))).toBe(
      "That address already has an account, in this or another organisation.",
    );
  });

  it("explains the removal refusals", () => {
    expect(errorText(new ApiError(422, "last_admin"))).toContain("last admin");
    expect(errorText(new ApiError(422, "platform_role"))).toContain("operator or content role");
    expect(errorText(new ApiError(422, "not_invited"))).toContain("already signed in");
  });

  it("names any other refusal by status and code", () => {
    expect(errorText(new ApiError(422, "tag_not_in_package"))).toBe(
      "Refused (422: tag_not_in_package).",
    );
    expect(errorText(new ApiError(500))).toBe("Refused (500).");
    expect(errorText(new Error("network"))).toBe("Something went wrong.");
    expect(errorText(null)).toBeNull();
  });
});
