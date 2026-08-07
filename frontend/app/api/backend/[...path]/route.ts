import "server-only";

const DEFAULT_LOCAL_BACKEND = "http://127.0.0.1:8000/api/v1";
const FORWARDED_REQUEST_HEADERS = new Set([
  "accept",
  "content-type",
  "if-none-match",
  "x-request-id",
]);
const FORWARDED_RESPONSE_HEADERS = new Set([
  "cache-control",
  "content-disposition",
  "content-length",
  "content-type",
  "etag",
  "pragma",
  "x-request-id",
]);

type RouteContext = { params: Promise<{ path: string[] }> | { path: string[] } };
type StreamingRequestInit = RequestInit & { duplex?: "half" };

function backendBaseUrl(): URL {
  const configured = process.env.BACKEND_API_BASE_URL?.trim();
  const raw = configured || (process.env.NODE_ENV === "development" ? DEFAULT_LOCAL_BACKEND : "");
  if (!raw) {
    throw new Error("BACKEND_API_BASE_URL is required outside local development.");
  }
  const url = new URL(raw.endsWith("/") ? raw : `${raw}/`);
  if (!new Set(["http:", "https:"]).has(url.protocol)) {
    throw new Error("BACKEND_API_BASE_URL must use HTTP or HTTPS.");
  }
  return url;
}

function backendToken(): string {
  const configured = process.env.API_AUTH_TOKEN?.trim();
  if (configured) return configured;
  if (process.env.NODE_ENV === "development") return "local-dev-token-change-me";
  throw new Error("API_AUTH_TOKEN is required outside local development.");
}

async function proxy(request: Request, context: RouteContext): Promise<Response> {
  try {
    const params = await context.params;
    const safeSegments = params.path.filter(
      (segment) => segment.length > 0 && segment !== "." && segment !== "..",
    );
    if (safeSegments.length !== params.path.length) {
      return Response.json(
        { code: "invalid_proxy_path", message: "Invalid backend path." },
        { status: 400 },
      );
    }

    const target = new URL(safeSegments.map(encodeURIComponent).join("/"), backendBaseUrl());
    target.search = new URL(request.url).search;

    const headers = new Headers();
    for (const [name, value] of request.headers) {
      if (FORWARDED_REQUEST_HEADERS.has(name.toLowerCase())) headers.set(name, value);
    }
    headers.set("authorization", `Bearer ${backendToken()}`);

    const hasBody = !new Set(["GET", "HEAD"]).has(request.method);
    const requestInit: StreamingRequestInit = {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      redirect: "manual",
      signal: request.signal,
    };
    if (hasBody && request.body) requestInit.duplex = "half";
    const upstream = await fetch(target, requestInit);

    const responseHeaders = new Headers();
    for (const [name, value] of upstream.headers) {
      if (FORWARDED_RESPONSE_HEADERS.has(name.toLowerCase())) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch {
    return Response.json(
      {
        code: "backend_proxy_unavailable",
        message: "The document service is not available.",
        retryable: true,
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
