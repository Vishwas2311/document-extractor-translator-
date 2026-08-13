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
  // The demo shell opens on the inspector's Page view, which server-renders the demo
  // result content in reading order: the referral block, then the structured table,
  // then the consent block. The result-card ids are unique to the inspector list, so
  // their positions are not confused with the thumbnail/viewer copies of the text.
  const referralPosition = html.indexOf("result-p1-concern");
  const tablePosition = html.indexOf("Structured table 1");
  const consentPosition = html.indexOf("result-p1-consent");
  assert.ok(referralPosition >= 0 && tablePosition > referralPosition && consentPosition > tablePosition);
  // The demo blocks' source text itself is present in the server-rendered shell.
  assert.match(html, /سبب الإحالة/);
  assert.match(html, /أوافق على استخدام/);
});

test("keeps credentials out of the client configuration", async () => {
  const [apiSource, proxySource, envExample, packageJson, pageSource, pdfPageSource, viteConfig, globalStyles] = await Promise.all([
    readFile(new URL("../app/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/backend/[...path]/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../.env.local.example", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/pdf-page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../vite.config.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(apiSource, /NEXT_PUBLIC_API_BASE_URL/);
  assert.doesNotMatch(apiSource, /NEXT_PUBLIC_API_AUTH_TOKEN|Authorization.*Bearer/i);
  assert.match(proxySource, /import "server-only"/);
  assert.match(proxySource, /process\.env\.API_AUTH_TOKEN/);
  assert.match(proxySource, /headers\.set\("authorization"/);
  assert.doesNotMatch(envExample, /NEXT_PUBLIC_.*(?:TOKEN|KEY|SECRET|PASSWORD)/i);
  assert.match(apiSource, /export function cancelDocument/);
  assert.match(apiSource, /status === "cancelled"/);
  const studioSource = await readFile(new URL("../app/document-studio.tsx", import.meta.url), "utf8");
  assert.match(studioSource, /await cancelDocument\(/);
  assert.match(studioSource, /status === "cancelled"/);
  assert.match(studioSource, /Format-preserving financial extraction/);
  assert.match(studioSource, /currentFinancialContentItems\.map/);
  assert.match(studioSource, /Reconstructed table structure/);
  assert.match(studioSource, /Accept structure/);
  assert.match(studioSource, /Accepted for review/);
  assert.match(studioSource, /Use Approve or Reject below to save the audit record/);
  assert.match(studioSource, /requires_currency_correction/);
  assert.match(studioSource, /Financial content language/);
  assert.match(studioSource, /Page content language/);
  assert.match(studioSource, /\(\["financial", "page", "json"\]/);
  assert.doesNotMatch(studioSource, /\(\["financial", "extracted", "translated", "json"\]/);
  assert.match(studioSource, /currentFinancialTableCount/);
  assert.match(studioSource, /aria-label="Service configuration"/);
  assert.match(studioSource, /diConfigured \? "Configured" : "Not configured"/);
  assert.doesNotMatch(envExample, /AZURE_.*KEY|API_KEY/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  assert.match(pageSource, /DocumentStudio/);
  assert.match(pdfPageSource, /Retry preview/);
  assert.match(pdfPageSource, /Document extraction continues independently/);
  assert.match(pdfPageSource, /pdfjs-dist\/webpack\.mjs/);
  assert.doesNotMatch(pdfPageSource, /workerSrc\s*=\s*["']\/pdf\.worker/);
  assert.match(viteConfig, /exclude: \["pdfjs-dist", "pdfjs-dist\/webpack\.mjs"\]/);
  assert.match(globalStyles, /\.global-header\s*\{[^}]*flex:\s*0 0 auto;/s);
  assert.match(globalStyles, /\.document-meta\s*\{[^}]*flex-wrap:\s*nowrap;[^}]*overflow:\s*hidden;/s);
  assert.match(globalStyles, /@media \(max-width: 1600px\)\s*\{[\s\S]*?\.service-copy\s*\{\s*display:\s*none;/);
  assert.match(globalStyles, /\.service-online,[\s\S]*?\.service-offline\s*\{[^}]*position:\s*absolute;/);
});
