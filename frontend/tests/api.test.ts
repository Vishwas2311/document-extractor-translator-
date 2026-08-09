import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, ApiValidationError, checkHealth, deleteDocument, parseErrorDetail } from "../app/lib/api";

/** Mimics real `fetch`: rejects when the passed `signal` aborts, otherwise hangs
 * forever (or resolves immediately if `body` is provided). Node's global `fetch`/
 * `Response`/`AbortController` (Node >=18, and this project requires >=26.3.0) are used
 * as-is - no polyfill needed. */
function mockFetch(options: { resolvesWith?: Response; rejectsWith?: unknown } = {}) {
  return vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
    return new Promise<Response>((resolve, reject) => {
      const signal = init?.signal;
      if (signal?.aborted) {
        reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
        return;
      }
      if (options.rejectsWith !== undefined) {
        reject(options.rejectsWith);
        return;
      }
      if (options.resolvesWith) {
        resolve(options.resolvesWith);
        return;
      }
      signal?.addEventListener("abort", () => {
        reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
      });
    });
  });
}

const validHealthPayload = {
  status: "ready",
  database: "ready",
  storage: "ready",
  worker: "ready",
  auth_required: true,
  default_processing_profile: "GENAI_PSEUDONYMIZED",
  default_data_class: "synthetic",
  limits: {
    max_upload_size_mb: 150,
    max_document_pages: 300,
    di_page_range_size: 50,
    di_range_concurrency: 2,
    translation_concurrency: 8,
    job_poll_timeout_minutes: 90,
  },
  azure_configured: { document_intelligence: true, openai: true },
  openai_deployment_configured: true,
};

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch({ resolvesWith: Response.json(validHealthPayload) }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parseErrorDetail", () => {
  it("returns a plain string detail verbatim", () => {
    expect(parseErrorDetail({ detail: "Document was not found." }, "fallback")).toBe(
      "Document was not found.",
    );
  });

  it("joins an array of string details", () => {
    expect(parseErrorDetail({ detail: ["a", "b"] }, "fallback")).toBe("a; b");
  });

  it("extracts msg from an array of validation-error objects", () => {
    expect(
      parseErrorDetail({ detail: [{ loc: ["body", "file"], msg: "Field required" }] }, "fallback"),
    ).toBe("Field required");
  });

  it("prefers message over detail when both are present", () => {
    expect(parseErrorDetail({ message: "Curated message." }, "fallback")).toBe("Curated message.");
  });

  it("falls back for a non-object payload", () => {
    expect(parseErrorDetail("just a string", "fallback")).toBe("fallback");
    expect(parseErrorDetail(null, "fallback")).toBe("fallback");
  });

  it("falls back when detail is missing entirely", () => {
    expect(parseErrorDetail({}, "fallback")).toBe("fallback");
  });
});

describe("performRequest via checkHealth - success path", () => {
  it("returns the validated payload on a 200 with a well-formed body", async () => {
    const result = await checkHealth();
    expect(result.status).toBe("ready");
  });

  it("throws ApiValidationError when the 200 body doesn't match the expected shape", async () => {
    vi.stubGlobal("fetch", mockFetch({ resolvesWith: Response.json({ unexpected: true }) }));
    await expect(checkHealth()).rejects.toThrow(ApiValidationError);
  });
});

describe("performRequest - non-ok responses without a curated `code`", () => {
  const cases: Array<[number, string]> = [
    [400, "Please complete all required fields."],
    [401, "Your session has expired. Please sign in again."],
    [403, "You don't have permission to perform this action."],
    [404, "We couldn't find what you're looking for."],
    [409, "This action conflicts with the current state of the document."],
    [413, "The selected file exceeds the allowed size."],
    [415, "The selected file is not supported."],
    [422, "Please complete all required fields."],
    [429, "You're sending requests too quickly. Please wait a moment and try again."],
    [502, "The service is temporarily unavailable. Please try again shortly."],
    [503, "The service is temporarily unavailable. Please try again shortly."],
    [504, "The request took longer than expected. Please try again."],
    [500, "Something went wrong. Please try again."],
    [418, "The request could not be completed."],
  ];

  for (const [status, expectedMessage] of cases) {
    it(`maps a bare ${status} (no code, framework-default detail array) to a safe generic message`, async () => {
      vi.stubGlobal(
        "fetch",
        mockFetch({
          resolvesWith: new Response(
            JSON.stringify({ detail: [{ loc: ["body"], msg: "some framework-internal validation text" }] }),
            { status },
          ),
        }),
      );
      const error = await checkHealth().catch((caught: unknown) => caught);
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).message).toBe(expectedMessage);
      expect((error as ApiError).status).toBe(status);
      // The raw framework validation text must never leak into the message.
      expect((error as ApiError).message).not.toContain("framework-internal");
    });
  }

  it("falls back to the generic status message for a non-JSON error body", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({ resolvesWith: new Response("<html>Bad Gateway</html>", { status: 502 }) }),
    );
    const error = await checkHealth().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("The service is temporarily unavailable. Please try again shortly.");
  });
});

describe("performRequest - non-ok responses WITH a curated `code`", () => {
  it("trusts the backend's own message, code, retryable, and request_id", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        resolvesWith: new Response(
          JSON.stringify({
            code: "document_not_found",
            message: "Document was not found.",
            retryable: false,
          }),
          { status: 404, headers: { "x-request-id": "req-123" } },
        ),
      }),
    );
    const error = await checkHealth().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.message).toBe("Document was not found.");
    expect(apiError.code).toBe("document_not_found");
    expect(apiError.status).toBe(404);
    expect(apiError.retryable).toBe(false);
    expect(apiError.requestId).toBe("req-123");
  });

  it("carries retryable:true through for a curated transient failure", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        resolvesWith: new Response(
          JSON.stringify({
            code: "azure_service_error",
            message: "Azure OpenAI translation failed.",
            retryable: true,
          }),
          { status: 502 },
        ),
      }),
    );
    const error = await checkHealth().catch((caught: unknown) => caught);
    expect((error as ApiError).retryable).toBe(true);
  });
});

describe("performRequest - network and timeout failures", () => {
  it("reports a connection failure when fetch() itself rejects", async () => {
    vi.stubGlobal("fetch", mockFetch({ rejectsWith: new TypeError("Failed to fetch") }));
    const error = await checkHealth().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe(
      "We couldn't connect to the server. Please check your connection and try again.",
    );
    expect((error as ApiError).retryable).toBe(true);
  });

  it("reports a timeout when the request outlives its timeoutMs", async () => {
    // No resolvesWith/rejectsWith - the mock hangs until the internal AbortController
    // fires its timeout, exactly like a stalled real connection would.
    vi.stubGlobal("fetch", mockFetch());
    const error = await checkHealth({ timeoutMs: 15 }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("The request took longer than expected. Please try again.");
    expect((error as ApiError).retryable).toBe(true);
  });

  it("propagates a caller-initiated cancellation as-is, not reframed as a network/timeout error", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const controller = new AbortController();
    const reason = new DOMException("Cancelled by caller", "AbortError");
    controller.abort(reason);
    const error = await checkHealth({ signal: controller.signal }).catch((caught: unknown) => caught);
    expect(error).toBe(reason);
    expect(error).not.toBeInstanceOf(ApiError);
  });
});

describe("apiFetchVoid - no body expected", () => {
  it("resolves without attempting to parse a body on success", async () => {
    vi.stubGlobal("fetch", mockFetch({ resolvesWith: new Response(null, { status: 204 }) }));
    await expect(deleteDocument("doc-1")).resolves.toBeUndefined();
  });
});
