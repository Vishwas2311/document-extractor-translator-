import { describe, expect, it } from "vitest";

import { selectInspectorBanner, type InspectorBannerState } from "../app/lib/inspector-banner";

function state(overrides: Partial<InspectorBannerState> = {}): InspectorBannerState {
  return {
    activeTab: "financial",
    hasFinancialContent: false,
    isDemo: false,
    hasPage: false,
    pageLoadError: null,
    hasActionError: false,
    documentStatus: "extracting",
    pageCount: 5,
    currentPageReady: false,
    financialExcluded: false,
    safeErrorMessage: null,
    ...overrides,
  };
}

describe("selectInspectorBanner", () => {
  it("shows 'unavailable' for a terminal failure with a curated message, on any tab but json", () => {
    const failure = state({ documentStatus: "failed", safeErrorMessage: "Azure OpenAI translation failed." });
    expect(selectInspectorBanner({ ...failure, activeTab: "financial" })).toBe("unavailable");
    expect(selectInspectorBanner({ ...failure, activeTab: "page" })).toBe("unavailable");
    expect(selectInspectorBanner({ ...failure, activeTab: "json" })).toBe(null);
  });

  it("also shows 'unavailable' for needs_review with a curated message, not just failed", () => {
    expect(
      selectInspectorBanner(
        state({ documentStatus: "needs_review", safeErrorMessage: "Some blocks need review." }),
      ),
    ).toBe("unavailable");
  });

  it("does not show 'unavailable' when the document is terminal but has no safe_error_message", () => {
    expect(selectInspectorBanner(state({ documentStatus: "failed", safeErrorMessage: null }))).not.toBe(
      "unavailable",
    );
  });

  it("'unavailable' takes priority over every other banner - the exact regression from this session", () => {
    // Previously this state rendered BOTH the "unavailable" banner AND the "empty"
    // banner simultaneously (or, before that fix, "still extracting" forever).
    const overlapProne = state({
      documentStatus: "failed",
      safeErrorMessage: "Translation failed.",
      currentPageReady: false,
    });
    expect(selectInspectorBanner(overlapProne)).toBe("unavailable");
  });

  it("shows 'excluded' when the page was not selected for financial extraction", () => {
    expect(selectInspectorBanner(state({ financialExcluded: true }))).toBe("excluded");
  });

  it("'excluded' does not require the document to be non-terminal or error-free", () => {
    // Mirrors the original inline condition, which never gated this banner on !error
    // or terminal status - only a faithful refactor, not a new behavior.
    expect(
      selectInspectorBanner(state({ financialExcluded: true, hasActionError: true, documentStatus: "completed" })),
    ).toBe("excluded");
  });

  it("shows 'extracting' while non-terminal, page not ready, and not excluded", () => {
    expect(
      selectInspectorBanner(state({ documentStatus: "extracting", currentPageReady: false, pageCount: 3 })),
    ).toBe("extracting");
  });

  it("does NOT show 'extracting' once the document reaches a terminal status", () => {
    // The bug fixed this session: this used to still show "still extracting" after the
    // backend had already marked the document failed/needs_review/completed/cancelled.
    for (const documentStatus of ["completed", "failed", "needs_review", "cancelled"] as const) {
      expect(
        selectInspectorBanner(state({ documentStatus, currentPageReady: false, pageCount: 3 })),
      ).not.toBe("extracting");
    }
  });

  it("does not show 'extracting' while an action error is already displayed", () => {
    expect(
      selectInspectorBanner(state({ hasActionError: true, currentPageReady: false, pageCount: 3 })),
    ).toBe(null);
  });

  it("shows 'loading' while non-terminal, page ready, page count known", () => {
    expect(selectInspectorBanner(state({ currentPageReady: true, pageCount: 3 }))).toBe("loading");
  });

  it("does NOT show 'loading' once the document reaches a terminal status", () => {
    expect(
      selectInspectorBanner(state({ documentStatus: "completed", currentPageReady: true, pageCount: 3 })),
    ).not.toBe("loading");
  });

  it("shows 'empty' for a terminal document with no page content and no curated error", () => {
    expect(
      selectInspectorBanner(state({ documentStatus: "completed", currentPageReady: false, safeErrorMessage: null })),
    ).toBe("empty");
  });

  it("does not show 'empty' when 'unavailable' already covers the same failed+message case", () => {
    // The second bug fixed this session: these two banners rendering together.
    expect(
      selectInspectorBanner(
        state({ documentStatus: "failed", currentPageReady: false, safeErrorMessage: "Translation failed." }),
      ),
    ).toBe("unavailable");
  });

  it("returns null once the full page JSON has loaded", () => {
    expect(selectInspectorBanner(state({ hasPage: true, currentPageReady: false, pageCount: 3 }))).toBe(null);
  });

  it("returns null when there's an independent page-load error", () => {
    expect(
      selectInspectorBanner(state({ pageLoadError: "Network error.", currentPageReady: false, pageCount: 3 })),
    ).toBe(null);
  });

  it("returns null for demo documents", () => {
    expect(selectInspectorBanner(state({ isDemo: true, currentPageReady: false, pageCount: 3 }))).toBe(null);
  });

  it("returns null on the financial tab once financial content is already showing", () => {
    expect(
      selectInspectorBanner(
        state({ activeTab: "financial", hasFinancialContent: true, currentPageReady: false, pageCount: 3 }),
      ),
    ).toBe(null);
  });

  it("still evaluates on the financial tab when it has no financial content yet", () => {
    expect(
      selectInspectorBanner(
        state({ activeTab: "financial", hasFinancialContent: false, currentPageReady: false, pageCount: 3 }),
      ),
    ).toBe("extracting");
  });

  it("always evaluates on the page and json tabs regardless of financial content", () => {
    expect(
      selectInspectorBanner(
        state({ activeTab: "page", hasFinancialContent: true, currentPageReady: false, pageCount: 3 }),
      ),
    ).toBe("extracting");
  });
});
