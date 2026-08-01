import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
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

test("server-renders the CareTranslate Studio shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /CareTranslate Studio/i);
  assert.match(html, /Care intelligence workspace/i);
  assert.match(html, /sample\.pdf/i);
  assert.match(html, /demo-thumbnail-page/i);
  assert.doesNotMatch(html, /react-loading-skeleton|Your site is taking shape/i);
  const referralPosition = html.indexOf("Reason for referral");
  const tablePosition = html.indexOf("Structured table 1");
  const consentPosition = html.indexOf("I consent to this information");
  assert.ok(referralPosition >= 0 && tablePosition > referralPosition && consentPosition > tablePosition);
});

test("keeps credentials out of the client configuration", async () => {
  const [apiSource, envExample, packageJson, pageSource, pdfPageSource, viteConfig] = await Promise.all([
    readFile(new URL("../app/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../.env.local.example", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/pdf-page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../vite.config.ts", import.meta.url), "utf8"),
  ]);

  assert.match(apiSource, /NEXT_PUBLIC_API_BASE_URL/);
  assert.doesNotMatch(envExample, /AZURE_.*KEY|API_KEY/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  assert.match(pageSource, /DocumentStudio/);
  assert.match(pdfPageSource, /Retry preview/);
  assert.match(pdfPageSource, /Document extraction continues independently/);
  assert.match(pdfPageSource, /pdfjs-dist\/webpack\.mjs/);
  assert.doesNotMatch(pdfPageSource, /workerSrc\s*=\s*["']\/pdf\.worker/);
  assert.match(viteConfig, /exclude: \["pdfjs-dist", "pdfjs-dist\/webpack\.mjs"\]/);
});
