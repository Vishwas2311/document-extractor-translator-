// Regression: connect-src had no blob: source. PDF.js re-fetches a document's
// source over the network from the blob: URL created for it (pdf-page.tsx's
// acquirePdfDocument) rather than reading the Blob object directly, and that
// fetch is governed by connect-src. Without blob: here, the browser blocked the
// fetch outright (no HTTP response at all) for every real (non-demo) document,
// surfacing as "Preview unavailable - Unexpected server response (0)" in the UI
// despite extraction/OCR/translation having succeeded. Found via live testing
// on 2026-08-12.
import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", String(process.pid) + "-" + String(Date.now()));
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("CSP connect-src allows blob: so PDF.js can fetch the document it was given", async () => {
  const response = await render();
  assert.equal(response.status, 200);

  const csp = response.headers.get("content-security-policy") ?? "";
  const connectSrcMatch = csp.match(/connect-src([^;]*)/);
  assert.ok(connectSrcMatch, `expected a connect-src directive, got: ${csp}`);
  assert.match(connectSrcMatch[1], /\bblob:/, `connect-src must allow blob:, got: ${connectSrcMatch[0]}`);
});
