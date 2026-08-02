import type {
  DocumentCreateResponse,
  DocumentDetail,
  DocumentListResponse,
  HealthStatus,
  PageResult,
  PageSummary,
} from "../types";
import {
  isDocumentCreateResponse,
  isDocumentDetail,
  isDocumentListResponse,
  isHealthStatus,
  isPageResult,
  isPageSummaryArray,
} from "./validation";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");

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
    const response = await fetch(endpoint(path), { ...init, signal: controller.signal });
    if (!response.ok) {
      let message = "Request failed with status " + response.status + ".";
      try {
        const payload = (await response.json()) as { detail?: string; message?: string };
        message = payload.detail ?? payload.message ?? message;
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
    "/documents/" + documentId,
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
    "/documents/" + documentId + "/pages/" + pageNumber,
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
    "/documents/" + documentId + "/pages",
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
  return apiFetchVoid("/documents/" + documentId, { method: "DELETE" }, options);
}

export function checkHealth(options?: RequestOptions): Promise<HealthStatus> {
  return apiFetch("/health/ready", isHealthStatus, "health status", undefined, options);
}

export function sourceUrl(documentId: string): string {
  return API_BASE + "/documents/" + documentId + "/source";
}

export function downloadUrl(
  documentId: string,
  artifact: "page" | "extracted" | "bilingual",
  pageNumber?: number,
): string {
  const query = artifact === "page" && pageNumber ? "?page=" + pageNumber : "";
  return API_BASE + "/documents/" + documentId + "/downloads/" + artifact + query;
}

export function retryDocument(
  documentId: string,
  options?: RequestOptions,
): Promise<DocumentCreateResponse> {
  return apiFetch(
    "/documents/" + documentId + "/retry",
    isDocumentCreateResponse,
    "document retry",
    { method: "POST" },
    options,
  );
}

export function isTerminal(status: DocumentDetail["status"]): boolean {
  return status === "completed" || status === "needs_review" || status === "failed";
}
