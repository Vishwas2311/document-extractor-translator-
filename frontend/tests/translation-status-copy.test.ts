import { describe, expect, it } from "vitest";

import { translationStatusCopy } from "../app/document-studio";

describe("translationStatusCopy", () => {
  it("does not double-prefix a warning the backend already labeled", () => {
    // Regression: processing.py stores block.warnings as "Translation failed: {reason}".
    // The label function used to wrap that in a second "Translation failed: " prefix.
    expect(
      translationStatusCopy("failed", [
        "Translation failed: Translation IDs did not match the input batch (missing, extra, or duplicate IDs).",
      ]),
    ).toBe(
      "Translation failed: Translation IDs did not match the input batch (missing, extra, or duplicate IDs).",
    );
  });

  it("still labels a warning with no existing prefix correctly", () => {
    expect(translationStatusCopy("failed", ["Azure OpenAI translation failed after retrying."])).toBe(
      "Translation failed: Azure OpenAI translation failed after retrying.",
    );
  });

  it("falls back to a generic message when there are no warnings", () => {
    expect(translationStatusCopy("failed", [])).toBe("Translation failed. Use Retry to try again.");
    expect(translationStatusCopy("failed", null)).toBe("Translation failed. Use Retry to try again.");
    expect(translationStatusCopy("failed", undefined)).toBe("Translation failed. Use Retry to try again.");
  });

  it("uses the last warning when there are multiple", () => {
    expect(translationStatusCopy("failed", ["first issue", "Translation failed: second issue"])).toBe(
      "Translation failed: second issue",
    );
  });

  it("handles the non-failed statuses unaffected by the prefix logic", () => {
    expect(translationStatusCopy("not_required")).toBe("No translatable text in this region.");
    expect(translationStatusCopy("pending")).toBe("Translation is queued and has not run yet.");
    expect(translationStatusCopy("filtered")).toBe(
      "Translation was filtered by the safety system and needs manual review.",
    );
    expect(translationStatusCopy("needs_review", ["Reviewer note"])).toBe("Reviewer note");
    expect(translationStatusCopy("needs_review")).toBe(
      "This region needs manual review before it can be translated.",
    );
  });
});
