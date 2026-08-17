// Regression: the hidden file-picker <input type="file"> used
// `className="visually-hidden"` (the screen-reader-only pattern, not
// display:none), so it stays keyboard-focusable and in the accessibility
// tree, but had no accessible name. A keyboard/screen-reader user tabbing
// through the page would land on an unlabeled file input. Found by manual
// QA on 2026-08-12.
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

test("the hidden upload file input has an accessible name", async () => {
  const response = await render();
  assert.equal(response.status, 200);

  const html = await response.text();
  const inputMatch = html.match(/<input[^>]*type="file"[^>]*>/);
  assert.ok(inputMatch, "expected a file input in the server-rendered shell");
  assert.match(inputMatch[0], /aria-label="Upload document"/);
});
