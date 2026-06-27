import { describe, it, expect } from "vitest";

import { middleware } from "./middleware";

/** Parse the CSP header into a directive → values map. */
function parseCsp(header: string | null): Record<string, string[]> {
  const map: Record<string, string[]> = {};
  if (!header) return map;
  for (const part of header.split(";")) {
    const [name, ...values] = part.trim().split(/\s+/);
    if (name) map[name] = values;
  }
  return map;
}

describe("middleware Content-Security-Policy", () => {
  it("allows external OAuth avatar images (Google/GitHub) via img-src", () => {
    const response = middleware();
    const csp = parseCsp(response.headers.get("Content-Security-Policy"));

    // OAuth providers serve avatars from their own HTTPS CDNs
    // (lh3.googleusercontent.com, avatars.githubusercontent.com).
    // img-src must permit external HTTPS sources or the avatar <img> is
    // blocked by the browser and the user's profile photo never renders.
    expect(csp["img-src"]).toContain("https:");
  });

  it("still applies the core hardening headers", () => {
    const response = middleware();
    expect(response.headers.get("X-Frame-Options")).toBe("DENY");
    expect(response.headers.get("X-Content-Type-Options")).toBe("nosniff");
  });
});
