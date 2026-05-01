import { useEffect, useState } from "react";
import { fetchCurrentUser } from "../api-client";
import type { UserProfile } from "../../../../shared/contracts/ts/v1/auth";

/** Fetches the current user profile on mount.
 *
 * If unauthenticated (or the request fails), redirects to ``/login`` —
 * this replaces the middleware-level redirect because the middleware
 * cannot see the API's cookie when API and frontend are on different
 * origins.
 */
export function useAuth() {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchCurrentUser()
      .then((profile) => {
        if (cancelled) return;
        if (!profile) {
          if (typeof window !== "undefined" && window.location.pathname !== "/login") {
            window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
          }
          return;
        }
        setUser(profile);
      })
      .catch(() => {
        if (cancelled) return;
        if (typeof window !== "undefined" && window.location.pathname !== "/login") {
          window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { user, loading };
}
