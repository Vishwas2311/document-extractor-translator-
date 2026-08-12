import type {
  DocumentCreateResponse,
  DocumentDetail,
  DocumentListResponse,
  HealthDependencies,
  HealthStatus,
  FinancialCorrection,
  FinancialReviewHistory,
  FinancialReviewRecord,
  FinancialStructureDecision,
  FinancialResult,
  PageResult,
  PageSummary,
  RetryMode,
  SessionStatus,
  TranslationCorrection,
  TranslationReviewHistory,
  TranslationReviewRecord,
} from "../types";
import {
  isDocumentCreateResponse,
  isDocumentDetail,
  isDocumentListResponse,
  isHealthDependencies,
  isHealthStatus,
  isFinancialResult,
  isFinancialReviewHistory,
  isFinancialReviewRecord,
  isPageResult,
  isPageSummaryArray,
  isSessionStatus,
  isTranslationReviewHistory,
  isTranslationReviewRecord,
} from "./validation";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/backend").replace(
  /\/$/,
  "",
);

const DEFAULT_TIMEOUT_MS = 30_000;

export interface RequestOptions {
  /** Cancels the request (and any related retry loop) - e.g. on unmount or a new upload. */
  signal?: AbortSignal;
  /** Overrides the default per-request timeout. */
  timeoutMs?: number;
}

export class ApiValidationError extends Error {
  constructor(context: string) {
    super(
      `The server returned an unexpected response for ${context}. Please retry, ` +
        "and contact support if this keeps happening.",
    );
    this.name = "ApiValidationError";
  }
}

/**
 * A failed request, carrying enough structure for callers to react to *what kind* of
 * failure occurred (e.g. show a retry affordance for 5xx, or a permission notice for
 * 403) without ever needing to inspect raw response text.
 */
export class ApiError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly requestId?: string;
  readonly retryable: boolean;

  constructor(
    message: string,
    options: { status?: number; code?: string; requestId?: string; retryable?: boolean } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId;
    this.retryable = options.retryable ?? false;
  }
}

/**
 * Generic, safe fallback copy per HTTP status. Used whenever the response body isn't a
 * curated `{code, message}` payload from our own backend (e.g. a framework-level 422,
 * a proxy/gateway error page, or a non-JSON body) — so a stray validation-error array or
 * an upstream HTML error page never renders verbatim in the UI.
 */
function friendlyMessageForStatus(status: number): string {
  switch (status) {
    case 400:
      return "Please complete all required fields.";
    case 401:
      return "Your session has expired. Please sign in again.";
    case 403:
      return "You don't have permission to perform this action.";
    case 404:
      return "We couldn't find what you're looking for.";
    case 409:
      return "This action conflicts with the current state of the document.";
    case 413:
      return "The selected file exceeds the allowed size.";
    case 415:
      return "The selected file is not supported.";
    case 422:
      return "Please complete all required fields.";
    case 429:
      return "You're sending requests too quickly. Please wait a moment and try again.";
    case 502:
    case 503:
      return "The service is temporarily unavailable. Please try again shortly.";
    case 504:
      return "The request took longer than expected. Please try again.";
    default:
      if (status >= 500) return "Something went wrong. Please try again.";
      return "The request could not be completed.";
  }
}

function endpoint(path: string): string {
  if (!API_BASE) {
    throw new Error("The Python backend is not connected. Set NEXT_PUBLIC_API_BASE_URL to enable real uploads.");
  }
  return API_BASE + path;
}

/**
 * FastAPI may return `detail` as a string, a validation-error array, or a structured
 * object. Flatten those shapes into a single user-facing message.
 */
export function parseErrorDetail(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const record = payload as Record<string, unknown>;
  const detail = record.detail ?? record.message;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const entry = item as Record<string, unknown>;
          if (typeof entry.msg === "string") return entry.msg;
          if (typeof entry.message === "string") return entry.message;
        }
        return null;
      })
      .filter((part): part is string => Boolean(part));
    if (parts.length) return parts.join("; ");
  }
  if (detail && typeof detail === "object") {
    const entry = detail as Record<string, unknown>;
    if (typeof entry.message === "string" && entry.message.trim()) return entry.message;
    if (typeof entry.msg === "string" && entry.msg.trim()) return entry.msg;
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return fallback;
}

/**
 * Fetches `path`, enforcing a request timeout and translating a non-2xx response into
 * a readable Error. Without a timeout, a single stalled request (a dropped connection,
 * a backend restart mid-response) hangs forever with no way to recover short of a full
 * page reload.
 */
async function performRequest(
  path: string,
  init?: RequestInit,
  options?: RequestOptions,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => {
    controller.abort(new DOMException("The request timed out.", "TimeoutError"));
  }, options?.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  const externalSignal = options?.signal;
  const onExternalAbort = () => controller.abort(externalSignal?.reason);
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort(externalSignal.reason);
    else externalSignal.addEventListener("abort", onExternalAbort);
  }

  try {
    let response: Response;
    try {
      response = await fetch(endpoint(path), { ...init, signal: controller.signal });
    } catch (fetchError: unknown) {
      if (externalSignal?.aborted) throw fetchError;
      if (controller.signal.aborted) {
        throw new ApiError("The request took longer than expected. Please try again.", {
          retryable: true,
        });
      }
      // fetch() itself rejected before a response arrived - DNS failure, refused
      // connection, offline, CORS block. There is no status/body to inspect.
      throw new ApiError(
        "We couldn't connect to the server. Please check your connection and try again.",
        { retryable: true },
      );
    }
    if (!response.ok) {
      const requestId = response.headers.get("x-request-id") ?? undefined;
      let code: string | undefined;
      let retryable = false;
      let message = friendlyMessageForStatus(response.status);
      try {
        const payload: unknown = await response.json();
        if (payload && typeof payload === "object") {
          const record = payload as Record<string, unknown>;
          if (typeof record.code === "string") code = record.code;
          if (typeof record.retryable === "boolean") retryable = record.retryable;
        }
        // Only trust the body's message when it came from our own backend's curated
        // error envelope (identified by the presence of `code`). Uncoded bodies -
        // framework-default validation arrays, proxy/gateway error pages - fall back
        // to the generic per-status copy above rather than rendering raw text.
        if (code) {
          message = parseErrorDetail(payload, message);
        }
      } catch {
        // Non-JSON body (e.g. an HTML error page from an intermediary) - keep the
        // generic per-status fallback.
      }
      throw new ApiError(message, { status: response.status, code, requestId, retryable });
    }
    return response;
  } finally {
    window.clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}

/**
 * Performs the request and validates the JSON body against `guard` before returning
 * it. Without the guard, a malformed response is trusted as `T` and only fails much
 * later, deep inside rendering, as an unrelated TypeError.
 */
async function apiFetch<T>(
  path: string,
  guard: (value: unknown) => value is T,
  context: string,
  init?: RequestInit,
  options?: RequestOptions,
): Promise<T> {
  const response = await performRequest(path, init, options);
  const payload: unknown = await response.json();
  if (!guard(payload)) {
    throw new ApiValidationError(context);
  }
  return payload;
}

/** Performs the request without expecting a JSON body back (e.g. a 204 DELETE). */
async function apiFetchVoid(
  path: string,
  init?: RequestInit,
  options?: RequestOptions,
): Promise<void> {
  await performRequest(path, init, options);
}

function documentPath(documentId: string, suffix = ""): string {
  return "/documents/" + encodeURIComponent(documentId) + suffix;
}

export function uploadDocument(
  file: File,
  options?: RequestOptions,
): Promise<DocumentCreateResponse> {
  const formData = new FormData();
  formData.append("file", file);
  // Large uploads legitimately take far longer than the default request timeout.
  // Scale with file size assuming a ~50 KB/s worst-case link, floored at 2 minutes
  // and capped at 30 minutes. The caller's abort signal (Cancel) still applies.
  const uploadTimeoutMs = Math.min(
    30 * 60_000,
    Math.max(120_000, Math.ceil(file.size / (50 * 1024)) * 1000),
  );
  return apiFetch(
    "/documents",
    isDocumentCreateResponse,
    "document upload",
    { method: "POST", body: formData },
    { ...options, timeoutMs: options?.timeoutMs ?? uploadTimeoutMs },
  );
}

export function getDocument(
  documentId: string,
  options?: RequestOptions,
): Promise<DocumentDetail> {
  return apiFetch(
    documentPath(documentId),
    isDocumentDetail,
    "document status",
    undefined,
    options,
  );
}

export function getPage(
  documentId: string,
  pageNumber: number,
  options?: RequestOptions,
): Promise<PageResult> {
  return apiFetch(
    documentPath(documentId, "/pages/" + pageNumber),
    isPageResult,
    "page result",
    undefined,
    options,
  );
}

/**
 * Lightweight per-page metadata (dimensions, block/table counts, review flag) for every
 * page in one request - used to populate the thumbnail rail instantly instead of
 * fetching every page's full extracted content up front. On a 70+ page document,
 * fetching full pages eagerly means 70 concurrent requests before anything renders;
 * this is one request, and full page content is then fetched on demand as the user
 * navigates (see `getPage`).
 */
export function listPageSummaries(
  documentId: string,
  options?: RequestOptions,
  view: "all" | "financial" | "review" = "all",
): Promise<PageSummary[]> {
  return apiFetch(
    documentPath(documentId, "/pages?view=" + encodeURIComponent(view)),
    isPageSummaryArray,
    "page list",
    undefined,
    options,
  );
}

export function getFinancialResult(
  documentId: string,
  options?: RequestOptions,
): Promise<FinancialResult> {
  return apiFetch(
    documentPath(documentId, "/financial-result"),
    isFinancialResult,
    "financial result",
    undefined,
    options,
  );
}

export function getFinancialReviews(
  documentId: string,
  options?: RequestOptions,
): Promise<FinancialReviewHistory> {
  return apiFetch(
    documentPath(documentId, "/financial-reviews"),
    isFinancialReviewHistory,
    "financial review history",
    undefined,
    options,
  );
}

export function createFinancialReview(
  documentId: string,
  review: {
    decision: "approved" | "rejected";
    note?: string | null;
    corrections: FinancialCorrection[];
    structure_decisions: FinancialStructureDecision[];
  },
  // Optimistic-concurrency guard: the server rejects a stale save (the result
  // changed underneath the reviewer) with 409 instead of silently overwriting
  // it. `null`/absent (e.g. a document's first-ever review, before a hash has
  // ever been persisted) skips the header - the server only requires it when
  // APP_ENV=production, which this local build never sets.
  ifMatch?: string | null,
  options?: RequestOptions,
): Promise<FinancialReviewRecord> {
  return apiFetch(
    documentPath(documentId, "/financial-reviews"),
    isFinancialReviewRecord,
    "financial review decision",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(ifMatch ? { "If-Match": `"${ifMatch}"` } : {}),
      },
      body: JSON.stringify(review),
    },
    options,
  );
}

export function getTranslationReviews(
  documentId: string,
  options?: RequestOptions,
): Promise<TranslationReviewHistory> {
  return apiFetch(
    documentPath(documentId, "/translation-reviews"),
    isTranslationReviewHistory,
    "translation review history",
    undefined,
    options,
  );
}

export function createTranslationReview(
  documentId: string,
  review: {
    decision: "approved" | "rejected";
    note?: string | null;
    corrections: TranslationCorrection[];
  },
  // See createFinancialReview's ifMatch comment - same optimistic-concurrency
  // contract, same reason `null`/absent is safe to send.
  ifMatch?: string | null,
  options?: RequestOptions,
): Promise<TranslationReviewRecord> {
  return apiFetch(
    documentPath(documentId, "/translation-reviews"),
    isTranslationReviewRecord,
    "translation review decision",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(ifMatch ? { "If-Match": `"${ifMatch}"` } : {}),
      },
      body: JSON.stringify(review),
    },
    options,
  );
}

export async function getBilingualDocument(
  documentId: string,
  options?: RequestOptions,
): Promise<Record<string, unknown>> {
  const response = await performRequest(
    documentPath(documentId, "/downloads/bilingual"),
    undefined,
    options,
  );
  return (await response.json()) as Record<string, unknown>;
}

export function listDocuments(
  page: number,
  pageSize: number,
  options?: RequestOptions,
): Promise<DocumentListResponse> {
  return apiFetch(
    "/documents?page=" + page + "&page_size=" + pageSize,
    isDocumentListResponse,
    "document list",
    undefined,
    options,
  );
}

export function deleteDocument(documentId: string, options?: RequestOptions): Promise<void> {
  return apiFetchVoid(documentPath(documentId), { method: "DELETE" }, options);
}

export function checkHealth(options?: RequestOptions): Promise<HealthStatus> {
  return apiFetch("/health/ready", isHealthStatus, "health status", undefined, options);
}

/**
 * Service-configuration flags (Document Intelligence / Azure OpenAI configured or
 * not). Deliberately separate from checkHealth(): /health/ready is unauthenticated
 * and content-free by design, so this detail lives behind auth on /health/dependencies.
 */
export function checkHealthDependencies(
  options?: RequestOptions,
): Promise<HealthDependencies> {
  return apiFetch(
    "/health/dependencies",
    isHealthDependencies,
    "health dependencies",
    undefined,
    options,
  );
}

export function checkSession(options?: RequestOptions): Promise<SessionStatus> {
  return apiFetch("/health/session", isSessionStatus, "session status", undefined, options);
}

/**
 * Path helper only — do not use as an `<img>`/`<iframe>`/`pdf.js` URL when auth is
 * required. Prefer `fetchSourceBlobUrl`, which sends the Authorization header.
 */
export function sourceUrl(documentId: string): string {
  return API_BASE + documentPath(documentId, "/source");
}

/**
 * Path helper only — do not open this URL in a new tab when auth is required.
 * Prefer `downloadArtifact`, which fetches with Authorization and saves a blob.
 */
export function downloadUrl(
  documentId: string,
  artifact:
    | "page"
    | "extracted"
    | "bilingual"
    | "reviewed-bilingual"
    | "manifest"
    | "financial"
    | "financial-csv"
    | "financial-xlsx"
    | "financial-validation",
  pageNumber?: number,
): string {
  const query = artifact === "page" && pageNumber ? "?page=" + pageNumber : "";
  return API_BASE + documentPath(documentId, "/downloads/" + artifact) + query;
}

/**
 * Fetches the source file with auth and returns an object URL suitable for pdf.js
 * or `<img src>`. Caller must revoke the URL when done.
 */
export async function fetchSourceBlobUrl(
  documentId: string,
  options?: RequestOptions,
): Promise<string> {
  const response = await performRequest(documentPath(documentId, "/source"), undefined, options);
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

export async function downloadArtifact(
  documentId: string,
  artifact:
    | "page"
    | "extracted"
    | "bilingual"
    | "reviewed-bilingual"
    | "manifest"
    | "financial"
    | "financial-csv"
    | "financial-xlsx"
    | "financial-validation",
  pageNumber?: number,
  options?: RequestOptions,
): Promise<void> {
  const query = artifact === "page" && pageNumber ? "?page=" + pageNumber : "";
  const response = await performRequest(
    documentPath(documentId, "/downloads/" + artifact) + query,
    undefined,
    options,
  );
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  // Only the RFC 5987 `filename*=UTF-8''...` form is percent-encoded; a plain
  // `filename="..."` may legitimately contain a stray `%`, so it must not be
  // percent-decoded (decodeURIComponent would throw a URIError).
  const encodedMatch = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const plainMatch = /filename="?([^";]+)"?/i.exec(disposition);
  let filename =
    artifact + (artifact === "page" && pageNumber ? "-" + pageNumber : "") + ".json";
  if (encodedMatch) {
    try {
      filename = decodeURIComponent(encodedMatch[1]);
    } catch {
      filename = encodedMatch[1];
    }
  } else if (plainMatch) {
    filename = plainMatch[1];
  }
  const url = URL.createObjectURL(blob);
  const link = window.document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  // Revoking immediately after click() can cancel a download that hasn't started
  // streaming yet; give the browser time to open the blob first.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function retryDocument(
  documentId: string,
  mode?: RetryMode,
  options?: RequestOptions,
): Promise<DocumentCreateResponse> {
  const query = mode ? "?mode=" + encodeURIComponent(mode) : "";
  return apiFetch(
    documentPath(documentId, "/retry") + query,
    isDocumentCreateResponse,
    "document retry",
    { method: "POST" },
    options,
  );
}

export function cancelDocument(
  documentId: string,
  options?: RequestOptions,
): Promise<{ document_id: string; status: string; message: string }> {
  return apiFetch(
    documentPath(documentId, "/cancel"),
    (value): value is { document_id: string; status: string; message: string } =>
      typeof value === "object" &&
      value !== null &&
      typeof (value as { document_id?: unknown }).document_id === "string" &&
      typeof (value as { status?: unknown }).status === "string" &&
      typeof (value as { message?: unknown }).message === "string",
    "document cancel",
    { method: "POST" },
    options,
  );
}

export function isTerminal(status: DocumentDetail["status"]): boolean {
  return (
    status === "completed" ||
    status === "needs_review" ||
    status === "failed" ||
    status === "cancelled"
  );
}

export function hasApiAuthToken(): boolean {
  // The server-side backend proxy owns authentication. The browser must never
  // receive or inspect the shared local API credential.
  return Boolean(API_BASE);
}
