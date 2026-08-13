// Regression: CSP `script-src` with no 'unsafe-inline' and no nonce blocked
// every inline hydration script the framework emits, breaking client-side
// interactivity (e.g. the Source/English toggle) with a "could not finish
// this Suspense boundary" error. Found by manual QA on 2026-08-12.
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

test("CSP nonce is present and matches every inline hydration script", async () => {
  const response = await render();
  assert.equal(response.status, 200);

  const csp = response.headers.get("content-security-policy") ?? "";
  const nonceMatch = csp.match(/script-src[^;]*'nonce-([^']+)'/);
  assert.ok(nonceMatch, `expected a nonce in script-src, got: ${csp}`);
  const nonce = nonceMatch[1];

  const html = await response.text();
  const inlineScripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>/gi)].map(([tag]) => tag);
  assert.ok(inlineScripts.length > 0, "expected inline hydration scripts in the server-rendered shell");

  const missingNonce = inlineScripts.filter((tag) => !tag.includes(`nonce="${nonce}"`));
  assert.deepEqual(missingNonce, [], "every inline script must carry the CSP nonce or the browser blocks it");
});
