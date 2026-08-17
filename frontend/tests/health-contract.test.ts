// Regression: HealthStatus/isHealthStatus required `azure_configured`, but
// /health/ready no longer returns it (that detail moved behind auth on
// /health/dependencies). Every real /health/ready response failed validation,
// checkHealth()'s .catch(() => undefined) swallowed the error silently, and the
// "Document extraction is not configured" / "Translation is not configured"
// UI hints permanently showed as unconfigured regardless of actual server state.
// This only surfaced on a backend process that had actually reloaded the change -
// the long-running dev backend used during the QA session had not, which is why
// live browser testing didn't catch it. Found via a second independent review.
import { describe, expect, it, vi } from "vitest";

import { checkHealth, checkHealthDependencies } from "../app/lib/api";
import { isHealthDependencies, isHealthStatus } from "../app/lib/validation";

function jsonResponse(body: unknown): Response {
  return Response.json(body);
}

describe("isHealthStatus", () => {
  it("accepts the real, current /health/ready shape (no azure_configured)", () => {
    expect(
      isHealthStatus({
        status: "ready",
        database: "ready",
        storage: "ready",
        worker: "ready",
        limits: { max_upload_size_mb: 150, max_document_pages: 300, job_poll_timeout_minutes: 90 },
      }),
    ).toBe(true);
  });

  it("accepts the minimal shape with no optional fields at all", () => {
    expect(isHealthStatus({ status: "ready" })).toBe(true);
  });

  it("rejects a payload missing status", () => {
    expect(isHealthStatus({ database: "ready" })).toBe(false);
  });
});

describe("isHealthDependencies", () => {
  it("accepts the real /health/dependencies shape", () => {
    expect(
      isHealthDependencies({
        document_intelligence: { configured: true, model: "prebuilt-layout", auth_mode: "api_key" },
        azure_openai: { configured: true, deployment: "gpt-5-mini", api: "v1", auth_mode: "api_key" },
        processing: { default_profile: "GENAI_PSEUDONYMIZED", default_data_class: "synthetic" },
      }),
    ).toBe(true);
  });

  it("accepts a deployment of null (unset) without failing validation", () => {
    expect(
      isHealthDependencies({
        document_intelligence: { configured: false },
        azure_openai: { configured: false, deployment: null },
      }),
    ).toBe(true);
  });

  it("rejects a payload missing the configured flags", () => {
    expect(isHealthDependencies({ document_intelligence: {}, azure_openai: {} })).toBe(false);
  });
});

describe("checkHealth and checkHealthDependencies against real backend shapes", () => {
  it("checkHealth resolves without throwing for the real /health/ready body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            status: "ready",
            database: "ready",
            storage: "ready",
            worker: "ready",
            limits: { max_upload_size_mb: 150, max_document_pages: 300 },
          }),
        ),
      ),
    );
    const result = await checkHealth();
    expect(result.status).toBe("ready");
    vi.unstubAllGlobals();
  });

  it("checkHealthDependencies resolves without throwing for the real /health/dependencies body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            document_intelligence: { configured: true, model: "prebuilt-layout", auth_mode: "api_key" },
            azure_openai: { configured: true, deployment: "gpt-5-mini", api: "v1", auth_mode: "api_key" },
            processing: { default_profile: "GENAI_PSEUDONYMIZED", default_data_class: "synthetic" },
          }),
        ),
      ),
    );
    const result = await checkHealthDependencies();
    expect(result.document_intelligence.configured).toBe(true);
    expect(result.azure_openai.configured).toBe(true);
    vi.unstubAllGlobals();
  });
});
