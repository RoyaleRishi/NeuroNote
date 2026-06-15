import { NextResponse } from "next/server";

/**
 * Content-Security-Policy applied to every response.
 *
 * Design decisions:
 *  - `unsafe-inline` + `unsafe-eval` in script-src: required by Next.js App
 *    Router inline hydration chunks and next/font inlining.
 *  - `wasm-unsafe-eval`: required by @mlc-ai/web-llm (Gemma WASM runtime).
 *  - `blob:` in script-src / worker-src: web-llm spawns Web Workers from
 *    Blob URLs at runtime.
 *  - `connect-src` includes the configured API origin (NEXT_PUBLIC_API_BASE_URL),
 *    plus broad `https:` / `wss:` so web-llm can fetch model weights from CDN
 *    and KaTeX can load remote resources.  Falls back to 'self' when the env
 *    var is absent (e.g. unit tests / CI).
 *  - `font-src data:`: KaTeX inlines fonts as data URIs.
 *  - `img-src blob:`: TipTap image extension and graph canvas produce blob URLs.
 *  - `frame-ancestors 'none'` / `object-src 'none'`: belt-and-suspenders
 *    clickjacking + plugin protection (X-Frame-Options: DENY covers legacy UA).
 */
const apiOrigin =
  process.env.NEXT_PUBLIC_API_BASE_URL
    ? new URL(process.env.NEXT_PUBLIC_API_BASE_URL).origin
    : null;

const connectSrc = ["'self'", apiOrigin, "https:", "wss:"]
  .filter(Boolean)
  .join(" ");

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob:",
  "worker-src 'self' blob:",
  `connect-src ${connectSrc}`,
].join("; ");

/** Pass-through middleware.
 *
 * The auth cookies are set by the API on a different origin than the Next.js
 * server (e.g. localhost:8000 vs localhost:3000), so the middleware cannot
 * see them.  Auth is enforced client-side by ``useAuth()`` calling
 * ``GET /v1/auth/me`` and redirecting to ``/login`` when unauthenticated.
 *
 * Security headers are applied to every matched response here so they're
 * enforced at the edge even for static assets that bypass API routes.
 */
export function middleware(): NextResponse {
  const response = NextResponse.next();

  // Prevent MIME-type sniffing attacks.
  response.headers.set("X-Content-Type-Options", "nosniff");

  // Block this page from being embedded in frames (legacy UA support;
  // CSP frame-ancestors covers modern browsers).
  response.headers.set("X-Frame-Options", "DENY");

  // Only send the origin when crossing from HTTPS→HTTPS; suppress on
  // downgrade to HTTP.
  response.headers.set(
    "Referrer-Policy",
    "strict-origin-when-cross-origin",
  );

  // Opt out of browser feature APIs that this app never uses.
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=()",
  );

  response.headers.set("Content-Security-Policy", CONTENT_SECURITY_POLICY);

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|robots.txt).*)"],
};
