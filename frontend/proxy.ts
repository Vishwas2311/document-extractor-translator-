import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Per-request CSP nonce so the RSC/SSR hydration scripts (inline <script>
// tags emitted by the framework) are allowed to run under a strict
// script-src that otherwise blocks all inline execution. Without a nonce
// on both the CSP header and the emitted scripts, the browser blocks every
// inline script and the app never hydrates (buttons and tabs stop working).
// Mirrors the documented Next.js pattern:
// https://nextjs.org/docs/app/guides/content-security-policy
function generateNonce(): string {
  // CSP3's nonce-source grammar is base64-value, not an arbitrary token - a raw
  // UUID (hyphenated) falls outside it. Browsers match the nonce as an opaque
  // string either way, but base64 keeps this spec-conformant instead of merely
  // working by browser leniency. btoa/crypto.getRandomValues are both available
  // as globals in the Cloudflare Worker runtime and in Node, no Buffer needed.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return btoa(String.fromCharCode(...bytes));
}

export function proxy(request: NextRequest) {
  const nonce = generateNonce();
  const cspHeader = [
    "default-src 'self'",
    `script-src 'self' 'wasm-unsafe-eval' 'nonce-${nonce}'`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    // blob: - PDF.js re-fetches the document over the network from the blob:
    // URL created for it (pdf-page.tsx's acquirePdfDocument), it doesn't just
    // read the Blob object directly. Without blob: here that fetch is blocked
    // outright (no HTTP response at all), which surfaces as a confusing
    // "Unexpected server response (0)" in the preview UI. Only same-tab,
    // self-created blob: URLs are ever fetchable - this doesn't open a route
    // to any externally-supplied URL, and mirrors the blob: already trusted by
    // img-src (image-document previews) and worker-src (the PDF.js worker) below.
    "connect-src 'self' blob:",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", cspHeader);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set("Content-Security-Policy", cspHeader);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
