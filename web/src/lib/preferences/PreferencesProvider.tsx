"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { fetchPreferences, updatePreferences } from "../api-client";
import type { UserPreferences, UpdatePreferencesRequest } from "../api-client";

/**
 * Single source of truth for the user's preferences (LLM mode, cloud config,
 * confidence threshold).
 *
 * Why a context: `usePreferences` used to be plain per-component `useState`, so
 * the header `UserMenu` and the `NotesWorkspace` editor each held a *separate*
 * copy. A mutation in the menu never reached the workspace, which is why
 * changes only appeared after a full page reload. Lifting state into one
 * provider means a single `mutate` updates every consumer in the same tick.
 */
export interface PreferencesContextValue {
  prefs: UserPreferences | null;
  loading: boolean;
  /** Re-fetch from the API (e.g. to recover from a failed initial load). */
  reload: () => Promise<void>;
  /**
   * Write `payload` through the API and adopt the server-canonical response as
   * local state. Returns the updated preferences. No second GET, no reload —
   * `updatePreferences` already returns the full updated object.
   */
  mutate: (payload: UpdatePreferencesRequest) => Promise<UserPreferences>;
}

const PreferencesContext = createContext<PreferencesContextValue | null>(null);

/**
 * Core preferences state machine, shared by the provider and the standalone
 * fallback. `active` gates the initial fetch so a fallback instance (rendered
 * outside a provider, e.g. in a unit test) stays inert when a real provider is
 * already present in the tree.
 */
export function usePreferencesState(active: boolean): PreferencesContextValue {
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [loading, setLoading] = useState(active);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setPrefs(await fetchPreferences());
    } catch {
      /* swallow — consumers fall back to defaults; reload() can retry */
    } finally {
      setLoading(false);
    }
  }, []);

  const mutate = useCallback(async (payload: UpdatePreferencesRequest) => {
    const updated = await updatePreferences(payload);
    setPrefs(updated);
    return updated;
  }, []);

  useEffect(() => {
    if (active) void reload();
  }, [active, reload]);

  return { prefs, loading, reload, mutate };
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const value = usePreferencesState(true);
  return (
    <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>
  );
}

/** Returns the provider value, or `null` when rendered outside a provider. */
export function usePreferencesContext(): PreferencesContextValue | null {
  return useContext(PreferencesContext);
}
