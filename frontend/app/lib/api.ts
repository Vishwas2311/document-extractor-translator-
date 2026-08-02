import type {
  DocumentCreateResponse,
  DocumentDetail,
  DocumentListResponse,
  HealthStatus,
  PageResult,
  PageSummary,
  RetryMode,
  SessionStatus,
} from "../types";
import {
  isDocumentCreateResponse,
  isDocumentDetail,
  isDocumentListResponse,
  isHealthStatus,
  isPageResult,
  isPageSummaryArray,
  isSessionStatus,
} from "./validation";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");

/** Local-only bearer token. Never place production secrets in NEXT_PUBLIC_*. */
const API_AUTH_TOKEN = (process.env.NEXT_PUBLIC_API_AUTH_TOKEN ?? "").trim();

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

function endpoint(path: string): string {
  if (!API_BASE) {
    throw new Error("The Python backend is not connected. Set NEXT_PUBLIC_API_BASE_URL to enable real uploads.");
  }
  return API_BASE + path;
}

function authHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init);
  if (API_AUTH_TOKEN && !headers.has("Authorization")) {
    headers.set("Authorization", "Bearer " + API_AUTH_TOKEN);
  }
  return headers;
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
    const headers = authHeaders(init?.headers);
    const response = await fetch(endpoint(path), { ...init, headers, signal: controller.signal });
    if (!response.ok) {
      let message = "Request failed with status " + response.status + ".";
      try {
        const payload: unknown = await response.json();
        message = parseErrorDetail(payload, message);
      } catch {
        // Keep the HTTP fallback when the service did not return JSON.
      }
      throw new Error(message);
    }
    return response;
  } catch (error) {
    if (externalSignal?.aborted) {
      // The caller cancelled us (unmount, superseded upload) - propagate as-is rather
      // than reframing it as a timeout or a generic failure.
      throw error;
    }
    if (controller.signal.aborted) {
      throw new Error("The request timed out. Check your connection and try again.");
    }
    throw error;
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
  return apiFetch(
    "/documents",
    isDocumentCreateResponse,
    "document upload",
    { method: "POST", body: formData },
    options,
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
): Promise<PageSummary[]> {
  return apiFetch(
    documentPath(documentId, "/pages"),
    isPageSummaryArray,
    "page list",
    undefined,
    options,
  );
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
  artifact: "page" | "extracted" | "bilingual",
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
  artifact: "page" | "extracted" | "bilingual",
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
  const matched = /filename\*?=(?:UTF-8''|")?([^\";]+)/i.exec(disposition);
  const filename = matched
    ? decodeURIComponent(matched[1].replace(/"/g, ""))
    : artifact + (artifact === "page" && pageNumber ? "-" + pageNumber : "") + ".json";
  const url = URL.createObjectURL(blob);
  try {
    const link = window.document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
  } finally {
    URL.revokeObjectURL(url);
  }
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

export function isTerminal(status: DocumentDetail["status"]): boolean {
  return status === "completed" || status === "needs_review" || status === "failed";
}

export function hasApiAuthToken(): boolean {
  return Boolean(API_AUTH_TOKEN);
}
