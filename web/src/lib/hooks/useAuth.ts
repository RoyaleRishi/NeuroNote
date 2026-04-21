import { useEffect, useState } from "react";
import { fetchCurrentUser } from "../api-client";
import type { UserProfile } from "../../../../shared/contracts/ts/v1/auth";

/** Fetches the current user profile on mount. Returns null while loading or if unauthenticated. */
export function useAuth() {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCurrentUser()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  return { user, loading };
}
