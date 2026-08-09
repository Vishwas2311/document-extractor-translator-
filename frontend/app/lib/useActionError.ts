"use client";

import { useState } from "react";
import type { SessionStatus } from "../types";
import { ApiError, checkSession } from "./api";

/**
 * Formats a caught error for display: the friendly message ApiError/Error already
 * carry, with a reference ID appended when the backend supplied one - so a user
 * reporting "it broke" can hand support a value that maps directly to a server log
 * line, without ever seeing raw exception text themselves.
 */
export function describeError(caught: unknown, fallback: string): string {
  if (!(caught instanceof Error)) return fallback;
  const requestId = caught instanceof ApiError ? caught.requestId : undefined;
  return requestId ? `${caught.message} (Reference ID: ${requestId})` : caught.message;
}

export interface UseActionErrorResult {
  error: string | null;
  errorRetry: (() => void) | null;
  sessionError: string | null;
  /** Keeps the error banner and its Retry affordance in sync - a Retry button must
   * never survive past the error it belonged to being cleared or replaced. */
  setActionError: (message: string | null, retry?: () => void) => void;
  /**
   * Routes a caught API failure to the right UI state: a 401 means every subsequent
   * request will also fail (not just this one), so it gets a distinct, persistent
   * banner rather than the generic per-action error - and re-checks the session so
   * session-derived UI reflects reality. This app has no login flow (the bearer token
   * is a server-side-only proxy credential, not a user session), so this intentionally
   * does not invent one - it names the problem as a hosting/config issue. Everything
   * else goes through the normal error banner, with a Retry button only when the
   * backend marked the failure `retryable` and the caller supplied a `retry`.
   */
  reportApiError: (
    caught: unknown,
    fallback: string,
    options?: { retry?: () => void },
  ) => Promise<void>;
  clearSessionError: () => void;
}

export function useActionError(
  onSessionRefreshed?: (session: SessionStatus) => void,
): UseActionErrorResult {
  const [error, setError] = useState<string | null>(null);
  const [errorRetry, setErrorRetry] = useState<(() => void) | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);

  function setActionError(message: string | null, retry?: () => void) {
    setError(message);
    setErrorRetry(message && retry ? () => retry : null);
  }

  async function reportApiError(
    caught: unknown,
    fallback: string,
    options?: { retry?: () => void },
  ) {
    if (caught instanceof ApiError && caught.status === 401) {
      try {
        const refreshed = await checkSession();
        onSessionRefreshed?.(refreshed);
      } catch {
        // Best-effort - the session banner below doesn't depend on this succeeding.
      }
      setSessionError(
        "This deployment's server-side credentials are misconfigured or expired. " +
          "This is a hosting configuration issue, not something fixable here - contact your administrator.",
      );
      return;
    }
    const retryable = caught instanceof ApiError && caught.retryable;
    setActionError(describeError(caught, fallback), retryable ? options?.retry : undefined);
  }

  return {
    error,
    errorRetry,
    sessionError,
    setActionError,
    reportApiError,
    clearSessionError: () => setSessionError(null),
  };
}
