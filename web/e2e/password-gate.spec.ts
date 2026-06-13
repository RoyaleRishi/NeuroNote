import { test } from "@playwright/test";

/**
 * Flow 11 — password gate.
 *
 * Skipped: the running Docker stack does not have `APP_PASSWORD` set, so
 * `web/src/middleware.ts` short-circuits and there's no gate to test.
 *
 * When `APP_PASSWORD` is set, the contract would be:
 *   1. GET / without a session cookie → 302 to /login?next=/
 *   2. POST /api/auth/login with { password } → 200 and a Set-Cookie for
 *      `neuronote_session` (httpOnly, sameSite=lax, no maxAge).
 *   3. GET / with the cookie → 200 and the workspace renders.
 *   4. POST /api/auth/logout → cookie cleared; next GET / redirects again.
 *
 * To enable this test, set APP_PASSWORD on the web service (see
 * infra/docker-compose.yml) and remove the skip below.
 */
test.skip(
  true,
  "password gate requires APP_PASSWORD on the web service; not set in dev",
);

test("redirects unauthenticated users to /login and accepts the password", async () => {
  // Intentionally empty — see file header.
});
