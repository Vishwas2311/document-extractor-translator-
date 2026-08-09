import type { DocumentStatus } from "../types";
import { isTerminal } from "./api";

export type InspectorBannerKind = "unavailable" | "excluded" | "extracting" | "loading" | "empty";

export interface InspectorBannerState {
  activeTab: "financial" | "page" | "json";
  hasFinancialContent: boolean;
  isDemo: boolean;
  hasPage: boolean;
  pageLoadError: string | null;
  hasActionError: boolean;
  documentStatus: DocumentStatus;
  pageCount: number | null;
  currentPageReady: boolean;
  financialExcluded: boolean;
  safeErrorMessage: string | null;
}

/**
 * Picks exactly one status banner for the inspector panel, or none. Two real bugs
 * shipped from this logic being four separately-maintained inline JSX conditions that
 * each grew their own exclusions ad hoc - a single pure selector with one return value
 * makes "more than one banner rendering at once" a type error, not a runtime surprise.
 */
export function selectInspectorBanner(state: InspectorBannerState): InspectorBannerKind | null {
  const {
    activeTab,
    hasFinancialContent,
    isDemo,
    hasPage,
    pageLoadError,
    hasActionError,
    documentStatus,
    pageCount,
    currentPageReady,
    financialExcluded,
    safeErrorMessage,
  } = state;

  const terminal = isTerminal(documentStatus);
  const failedOrNeedsReview = documentStatus === "failed" || documentStatus === "needs_review";

  // Independent of tab/page state: a terminal failure with a curated message always
  // wins, on every tab except the raw JSON view.
  if (activeTab !== "json" && failedOrNeedsReview && safeErrorMessage) {
    return "unavailable";
  }

  // Everything below only applies once the full page JSON hasn't loaded yet, there's no
  // independent page-load error already covering this state, and (on the financial tab)
  // there's no financial content already rendering below the banner.
  const relevantForTab = activeTab !== "financial" || !hasFinancialContent;
  if (!relevantForTab || isDemo || hasPage || pageLoadError) return null;

  if (financialExcluded) return "excluded";
  if (hasActionError) return null;

  if (!terminal && pageCount && !currentPageReady) return "extracting";
  if (!terminal && currentPageReady && pageCount) return "loading";
  if (terminal && !currentPageReady && !(failedOrNeedsReview && safeErrorMessage)) return "empty";

  return null;
}
