"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchPreferences } from "../api-client";
import type { UserPreferences } from "../api-client";

/**
 * Loads user preferences from the API on mount.
 * Returns the current preferences, loading state, and a reload function.
 */
export function usePreferences() {
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = await fetchPreferences();
      setPrefs(p);
    } catch {
      /* silently ignore — caller can retry via reload */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return { prefs, loading, reload: load };
}
