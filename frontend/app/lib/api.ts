import type {
  DocumentCreateResponse,
  DocumentDetail,
  PageResult,
} from "../types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");

function endpoint(path: string): string {
  if (!API_BASE) {
    throw new Error("The Python backend is not connected. Set NEXT_PUBLIC_API_BASE_URL to enable real uploads.");
  }
  return API_BASE + path;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(endpoint(path), init);
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
  return (await response.json()) as T;
}

export function uploadDocument(file: File): Promise<DocumentCreateResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<DocumentCreateResponse>("/documents", {
    method: "POST",
    body: formData,
  });
}

export function getDocument(documentId: string): Promise<DocumentDetail> {
  return apiFetch<DocumentDetail>("/documents/" + documentId);
}

export function getPage(documentId: string, pageNumber: number): Promise<PageResult> {
  return apiFetch<PageResult>("/documents/" + documentId + "/pages/" + pageNumber);
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

export function retryDocument(documentId: string): Promise<DocumentCreateResponse> {
  return apiFetch<DocumentCreateResponse>("/documents/" + documentId + "/retry", {
    method: "POST",
  });
}

export function isTerminal(status: DocumentDetail["status"]): boolean {
  return status === "completed" || status === "needs_review" || status === "failed";
}
