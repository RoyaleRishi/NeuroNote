import { NextResponse } from "next/server";

/** Pass-through middleware.
 *
 * The auth cookies are set by the API on a different origin than the Next.js
 * server (e.g. localhost:8000 vs localhost:3000), so the middleware cannot
 * see them.  Auth is enforced client-side by ``useAuth()`` calling
 * ``GET /v1/auth/me`` and redirecting to ``/login`` when unauthenticated.
 */
export function middleware(): NextResponse {
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|robots.txt).*)"],
};
