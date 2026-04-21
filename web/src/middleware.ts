import { NextRequest, NextResponse } from "next/server";

const AUTH_COOKIE = "neuronote_access";

/** Prefixes that bypass the auth gate entirely. */
const PUBLIC_PREFIXES = ["/login", "/api/", "/_next/"];

export function middleware(req: NextRequest): NextResponse {
  const { pathname } = req.nextUrl;

  // Allow public paths through without checking auth.
  if (PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // If the JWT access cookie is present, allow the request.
  // Actual token validation happens server-side in the API.
  if (req.cookies.has(AUTH_COOKIE)) {
    return NextResponse.next();
  }

  // No cookie — redirect to login, preserving the intended destination.
  const loginUrl = new URL("/login", req.url);
  loginUrl.searchParams.set("next", pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  // Run on all routes except Next.js internals and static files.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|robots.txt).*)"],
};
