"use client";

import {
  usePreferencesContext,
  usePreferencesState,
  type PreferencesContextValue,
} from "../preferences/PreferencesProvider";

/**
 * Access shared user preferences.
 *
 * Prefers the app-wide {@link PreferencesProvider} (so every consumer reflects
 * a mutation immediately). When rendered without a provider — standalone unit
 * tests — it transparently falls back to a local instance so the component
 * still works in isolation. The fallback's initial fetch only runs when no
 * provider is present, avoiding a duplicate request in the real app.
 */
export function usePreferences(): PreferencesContextValue {
  const ctx = usePreferencesContext();
  const fallback = usePreferencesState(ctx === null);
  return ctx ?? fallback;
}
