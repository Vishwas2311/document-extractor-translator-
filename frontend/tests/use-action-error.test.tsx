import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../app/lib/api";
import { useActionError } from "../app/lib/useActionError";

vi.mock("../app/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/lib/api")>();
  return {
    ...actual,
    checkSession: vi.fn().mockResolvedValue({ authenticated: true, auth_required: true }),
  };
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useActionError", () => {
  it("setActionError sets the message with no retry by default", () => {
    const { result } = renderHook(() => useActionError());
    act(() => result.current.setActionError("Something failed."));
    expect(result.current.error).toBe("Something failed.");
    expect(result.current.errorRetry).toBe(null);
  });

  it("setActionError attaches a retry callback when supplied", () => {
    const { result } = renderHook(() => useActionError());
    const retry = vi.fn();
    act(() => result.current.setActionError("Something failed.", retry));
    expect(result.current.errorRetry).toBeTypeOf("function");
    result.current.errorRetry?.();
    expect(retry).toHaveBeenCalledOnce();
  });

  it("setActionError(null) clears both the message and the retry callback together", () => {
    const { result } = renderHook(() => useActionError());
    act(() => result.current.setActionError("Something failed.", vi.fn()));
    expect(result.current.errorRetry).not.toBe(null);
    act(() => result.current.setActionError(null));
    expect(result.current.error).toBe(null);
    expect(result.current.errorRetry).toBe(null);
  });

  it("reportApiError with a plain Error sets the generic error banner, not the session banner", async () => {
    const { result } = renderHook(() => useActionError());
    await act(async () => {
      await result.current.reportApiError(new Error("plain failure"), "Fallback message.");
    });
    expect(result.current.error).toBe("plain failure");
    expect(result.current.sessionError).toBe(null);
  });

  it("reportApiError with a 401 ApiError sets the session banner, not the generic error banner", async () => {
    const onSessionRefreshed = vi.fn();
    const { result } = renderHook(() => useActionError(onSessionRefreshed));
    const unauthorized = new ApiError("Your session has expired. Please sign in again.", {
      status: 401,
    });
    await act(async () => {
      await result.current.reportApiError(unauthorized, "Fallback message.");
    });
    expect(result.current.sessionError).toMatch(/hosting configuration issue/);
    expect(result.current.error).toBe(null);
    expect(onSessionRefreshed).toHaveBeenCalledOnce();
  });

  it("clearSessionError clears only the session banner", async () => {
    const { result } = renderHook(() => useActionError());
    await act(async () => {
      await result.current.reportApiError(new ApiError("expired", { status: 401 }), "fallback");
    });
    expect(result.current.sessionError).not.toBe(null);
    act(() => result.current.clearSessionError());
    expect(result.current.sessionError).toBe(null);
  });

  it("reportApiError wires a Retry callback only when the ApiError is retryable", async () => {
    const { result } = renderHook(() => useActionError());
    const retry = vi.fn();
    const retryableError = new ApiError("Service unavailable.", { status: 503, retryable: true });
    await act(async () => {
      await result.current.reportApiError(retryableError, "fallback", { retry });
    });
    expect(result.current.errorRetry).toBeTypeOf("function");
  });

  it("reportApiError does NOT wire a Retry callback for a non-retryable ApiError", async () => {
    const { result } = renderHook(() => useActionError());
    const retry = vi.fn();
    const permanentError = new ApiError("Not found.", { status: 404, retryable: false });
    await act(async () => {
      await result.current.reportApiError(permanentError, "fallback", { retry });
    });
    expect(result.current.errorRetry).toBe(null);
  });

  it("reportApiError appends the reference ID from the backend when present", async () => {
    const { result } = renderHook(() => useActionError());
    const error = new ApiError("Translation failed.", { status: 502, requestId: "req-abc" });
    await act(async () => {
      await result.current.reportApiError(error, "fallback");
    });
    expect(result.current.error).toBe("Translation failed. (Reference ID: req-abc)");
  });
});
