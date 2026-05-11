/**
 * localStorage helpers for edge-mode UX state.
 *
 * Two keys, both safe against private-mode localStorage failures and
 * malformed values:
 *   - neuronote:edge-consent: "accepted" | "declined" | absent
 *   - neuronote:edge-init-pending: { startedAt: <unix-ms> } | absent
 *
 * Pure module — no React, no DOM beyond `window.localStorage`.
 */

export const CONSENT_KEY = "neuronote:edge-consent";
export const PENDING_KEY = "neuronote:edge-init-pending";

/** A pending flag older than this is treated as a stale walk-away, not a crash. */
export const STALE_PENDING_MS = 60 * 60 * 1000;

export type ConsentValue = "accepted" | "declined";

export interface PendingFlag {
  startedAt: number;
}

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // private-mode / quota — silently drop.
  }
}

function safeRemove(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // private-mode / quota — removal cannot throw into callers.
  }
}

export function readConsent(): ConsentValue | null {
  const raw = safeGet(CONSENT_KEY);
  if (raw === "accepted" || raw === "declined") return raw;
  return null;
}

export function writeConsent(value: ConsentValue): void {
  safeSet(CONSENT_KEY, value);
}

export function clearConsent(): void {
  safeRemove(CONSENT_KEY);
}

export function readPendingFlag(): PendingFlag | null {
  const raw = safeGet(PENDING_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed &&
      typeof parsed === "object" &&
      "startedAt" in parsed &&
      typeof (parsed as { startedAt: unknown }).startedAt === "number"
    ) {
      return { startedAt: (parsed as { startedAt: number }).startedAt };
    }
    return null;
  } catch {
    return null;
  }
}

export function writePendingFlag(startedAt: number): void {
  safeSet(PENDING_KEY, JSON.stringify({ startedAt }));
}

export function clearPendingFlag(): void {
  safeRemove(PENDING_KEY);
}
