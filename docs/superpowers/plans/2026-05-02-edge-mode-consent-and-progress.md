# Edge Mode Consent + Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop edge AI mode from surprise-reloading the page, recover gracefully when it does, and make 30–60s processing feel like progress instead of a frozen badge.

**Architecture:** Two new persistent flags (`edge-consent`, `edge-init-pending`) gate the edge engine in `useEdgeLLM`. A consent dialog and a crash-recovery banner render from `NotesWorkspace`. Two new streaming callbacks on `runEdgeProcessing` feed per-chunk progress and live concept names into the existing toolbar via a new `LiveConceptsPreview` pill.

**Tech Stack:** TypeScript, React 18, Vitest + @testing-library/react, no new runtime dependencies.

---

## Spec reference

This plan implements `docs/superpowers/specs/2026-05-02-edge-mode-consent-and-progress-design.md`. Re-read that spec when type signatures or behaviors look ambiguous.

## File structure

**New files:**

- `web/src/lib/edge-llm/persistence.ts` — Reading/writing the two localStorage keys with safe parsing and stale-age check. Pure module; no React.
- `web/src/lib/edge-llm/__tests__/persistence.test.ts`
- `web/src/components/llm/EdgeConsentDialog.tsx` — Modal asking user to choose edge or cloud mode.
- `web/src/components/llm/EdgeCrashBanner.tsx` — Banner shown after a crash-induced reload.
- `web/src/components/llm/LiveConceptsPreview.tsx` — Toolbar pill + popover listing concepts as they stream in.
- `web/src/components/llm/__tests__/EdgeConsentDialog.test.tsx`
- `web/src/components/llm/__tests__/EdgeCrashBanner.test.tsx`
- `web/src/components/llm/__tests__/LiveConceptsPreview.test.tsx`

**Modified files:**

- `web/src/lib/edge-llm/model-manager.ts` — `ModelStatus` adds `"awaiting-consent"` and `"awaiting-recovery"`.
- `web/src/lib/hooks/useEdgeLLM.ts` — Reads consent + crash flag, exposes new state and four new functions.
- `web/src/lib/orchestration/edge-processing.ts` — Adds `onChunkResult` callback.
- `web/src/components/editor/StatusBadge.tsx` — `ProcessStatusBadge` accepts optional `progress`.
- `web/src/components/editor/EditorToolbar.tsx` — Forwards new `progress` and `liveConcepts` props.
- `web/src/components/editor/NoteEditor.tsx` — Two new state slots (`processProgress`, `liveConcepts`); wires the new callbacks; calls `markStableInference` after first successful run.
- `web/src/components/workspace/NotesWorkspace.tsx` — Renders `EdgeConsentDialog` and `EdgeCrashBanner`; passes hook accept/decline/acknowledge handlers.

---

## Type contracts (used across tasks)

These appear in multiple tasks. Keep them in sync.

```typescript
// web/src/lib/edge-llm/persistence.ts
export type ConsentValue = "accepted" | "declined";

export interface PendingFlag {
  startedAt: number; // Date.now() ms
}

// web/src/lib/edge-llm/model-manager.ts
export type ModelStatus =
  | "idle"
  | "awaiting-consent"   // NEW
  | "awaiting-recovery"  // NEW
  | "downloading"
  | "ready"
  | "error"
  | "unsupported";

// web/src/lib/hooks/useEdgeLLM.ts (return shape)
export interface UseEdgeLLMResult {
  status: ModelStatus;
  progress: ModelProgress | null;
  error: string | null;
  isReady: boolean;
  acceptConsent: () => void;
  declineConsent: () => void;
  acknowledgeRecovery: (action: "retry" | "switchToCloud") => void;
  markStableInference: () => void;
}

// web/src/lib/orchestration/edge-processing.ts
// EdgeProcessingRequest gains:
onChunkResult?: (chunkConcepts: string[]) => void;

// NoteEditor in-memory state
// processProgress: { done: number; total: number } | null
// liveConcepts: string[]
```

---

## Task 1: Persistence helpers (pure module + tests)

**Files:**
- Create: `web/src/lib/edge-llm/persistence.ts`
- Create: `web/src/lib/edge-llm/__tests__/persistence.test.ts`

- [ ] **Step 1: Write failing tests**

Create `web/src/lib/edge-llm/__tests__/persistence.test.ts`:

```typescript
import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  CONSENT_KEY,
  PENDING_KEY,
  STALE_PENDING_MS,
  readConsent,
  writeConsent,
  clearConsent,
  readPendingFlag,
  writePendingFlag,
  clearPendingFlag,
} from "../persistence";

describe("edge-llm/persistence", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  describe("consent", () => {
    it("returns null when nothing is stored", () => {
      expect(readConsent()).toBeNull();
    });

    it("round-trips 'accepted'", () => {
      writeConsent("accepted");
      expect(readConsent()).toBe("accepted");
      expect(window.localStorage.getItem(CONSENT_KEY)).toBe("accepted");
    });

    it("round-trips 'declined'", () => {
      writeConsent("declined");
      expect(readConsent()).toBe("declined");
    });

    it("returns null for unknown stored values", () => {
      window.localStorage.setItem(CONSENT_KEY, "garbage");
      expect(readConsent()).toBeNull();
    });

    it("clearConsent removes the entry", () => {
      writeConsent("accepted");
      clearConsent();
      expect(readConsent()).toBeNull();
    });
  });

  describe("pending flag", () => {
    it("returns null when nothing is stored", () => {
      expect(readPendingFlag()).toBeNull();
    });

    it("round-trips an object", () => {
      writePendingFlag(123456);
      const got = readPendingFlag();
      expect(got).toEqual({ startedAt: 123456 });
    });

    it("returns null for malformed JSON", () => {
      window.localStorage.setItem(PENDING_KEY, "{not json");
      expect(readPendingFlag()).toBeNull();
    });

    it("returns null when startedAt is not a number", () => {
      window.localStorage.setItem(
        PENDING_KEY,
        JSON.stringify({ startedAt: "yesterday" }),
      );
      expect(readPendingFlag()).toBeNull();
    });

    it("clearPendingFlag removes the entry", () => {
      writePendingFlag(Date.now());
      clearPendingFlag();
      expect(readPendingFlag()).toBeNull();
    });
  });

  describe("STALE_PENDING_MS", () => {
    it("equals one hour", () => {
      expect(STALE_PENDING_MS).toBe(60 * 60 * 1000);
    });
  });

  describe("localStorage unavailable", () => {
    it("read functions return null when localStorage throws", () => {
      const spy = vi
        .spyOn(window.localStorage.__proto__, "getItem")
        .mockImplementation(() => {
          throw new Error("private mode");
        });
      expect(readConsent()).toBeNull();
      expect(readPendingFlag()).toBeNull();
      spy.mockRestore();
    });

    it("write functions swallow errors", () => {
      const spy = vi
        .spyOn(window.localStorage.__proto__, "setItem")
        .mockImplementation(() => {
          throw new Error("quota exceeded");
        });
      expect(() => writeConsent("accepted")).not.toThrow();
      expect(() => writePendingFlag(1)).not.toThrow();
      spy.mockRestore();
    });
  });
});
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd web && npx vitest run src/lib/edge-llm/__tests__/persistence.test.ts`
Expected: FAIL — `Cannot find module '../persistence'`.

- [ ] **Step 3: Implement**

Create `web/src/lib/edge-llm/persistence.ts`:

```typescript
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
    // ignore
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
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/lib/edge-llm/__tests__/persistence.test.ts`
Expected: 13/13 pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/edge-llm/persistence.ts web/src/lib/edge-llm/__tests__/persistence.test.ts
git commit -m "$(cat <<'EOF'
edge-llm: localStorage helpers for consent + pending flag

Pure module with safe-get/set helpers that survive private-mode
quota errors and malformed values. Stable key names exported as
constants so the React layers can refer to them by symbol.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Extend ModelStatus with awaiting-consent and awaiting-recovery

**Files:**
- Modify: `web/src/lib/edge-llm/model-manager.ts`

- [ ] **Step 1: Read current ModelStatus**

Run: `grep -n "ModelStatus" web/src/lib/edge-llm/model-manager.ts`
Note the current type definition lines.

- [ ] **Step 2: Replace the type definition**

Find the existing `ModelStatus` definition (it currently lists `"idle" | "downloading" | "ready" | "error" | "unsupported"`). Replace with:

```typescript
export type ModelStatus =
  | "idle"
  | "awaiting-consent"
  | "awaiting-recovery"
  | "downloading"
  | "ready"
  | "error"
  | "unsupported";
```

- [ ] **Step 3: Verify TypeScript**

Run: `cd web && npx tsc --noEmit`
Expected: clean. (No consumer of `ModelStatus` exhaustively switches — they only check specific values, so adding members is safe.)

- [ ] **Step 4: Run all tests**

Run: `cd web && npx vitest run`
Expected: all tests still pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/edge-llm/model-manager.ts
git commit -m "$(cat <<'EOF'
edge-llm: extend ModelStatus with awaiting-consent and awaiting-recovery

Two new statuses that sit between 'idle' and 'downloading' to gate
engine init on user choices. No existing consumer switches
exhaustively, so this is additive.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Extend useEdgeLLM hook with consent + crash gating

**Files:**
- Modify: `web/src/lib/hooks/useEdgeLLM.ts`

- [ ] **Step 1: Read the current hook**

Run: `cat web/src/lib/hooks/useEdgeLLM.ts`. The current hook accepts `(enabled: boolean, retryToken: number)` and returns `{ status, progress, error, isReady }`. We're adding consent gating, crash detection, and four imperative methods.

- [ ] **Step 2: Replace the file**

Overwrite `web/src/lib/hooks/useEdgeLLM.ts` with:

```typescript
"use client";

/**
 * React hook owning the WebLLM engine lifecycle plus two UX gates:
 *
 *   1. Consent gating — first time edge mode is selected, hold the
 *      engine in 'awaiting-consent' until the user accepts or declines.
 *   2. Crash detection — if a previous session set the
 *      'edge-init-pending' flag and never cleared it, hold the engine
 *      in 'awaiting-recovery' until the user dismisses or switches.
 *
 * Both flags are persisted via `lib/edge-llm/persistence.ts`. The flag
 * for crash detection is set just before `initializeEngine()` and
 * cleared by the caller via `markStableInference()` after the first
 * successful inference completes.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  initializeEngine,
  isWebGPUSupported,
  type ModelProgress,
  type ModelStatus,
} from "../edge-llm/model-manager";
import {
  readConsent,
  writeConsent,
  readPendingFlag,
  writePendingFlag,
  clearPendingFlag,
  STALE_PENDING_MS,
} from "../edge-llm/persistence";

export interface UseEdgeLLMResult {
  status: ModelStatus;
  progress: ModelProgress | null;
  error: string | null;
  /** True once the engine has finished downloading and is ready for inference. */
  isReady: boolean;
  /** Called when the user accepts the consent dialog. Persists choice + starts init. */
  acceptConsent: () => void;
  /** Called when the user declines. Persists choice. Caller switches mode to cloud. */
  declineConsent: () => void;
  /** Dismiss the crash banner; either retry or switch to cloud. */
  acknowledgeRecovery: (action: "retry" | "switchToCloud") => void;
  /** Caller invokes after the first successful inference to clear the crash flag. */
  markStableInference: () => void;
}

export function useEdgeLLM(
  enabled: boolean,
  retryToken: number = 0,
): UseEdgeLLMResult {
  const [status, setStatus] = useState<ModelStatus>("idle");
  const [progress, setProgress] = useState<ModelProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Token bumped to retry the gating + init sequence after consent / recovery.
  const [internalToken, setInternalToken] = useState(0);

  // Whether the user has already cleared the pending flag this session — used
  // to avoid a second 'awaiting-recovery' after they retried.
  const recoveryHandledRef = useRef(false);

  const startInit = useCallback(() => {
    if (!isWebGPUSupported()) {
      setStatus("unsupported");
      setError("WebGPU is not available in this browser.");
      return;
    }
    setError(null);
    writePendingFlag(Date.now());
    void initializeEngine(
      (p) => setProgress(p),
      (s) => setStatus(s),
      (msg) => setError(msg),
    );
  }, []);

  useEffect(() => {
    if (!enabled) {
      setStatus("idle");
      return;
    }

    // 1. Consent gate.
    const consent = readConsent();
    if (consent !== "accepted") {
      setStatus("awaiting-consent");
      return;
    }

    // 2. Crash gate (only once per session).
    if (!recoveryHandledRef.current) {
      const pending = readPendingFlag();
      if (pending) {
        const age = Date.now() - pending.startedAt;
        if (age < STALE_PENDING_MS) {
          setStatus("awaiting-recovery");
          return;
        }
        // Stale — silently clear and proceed.
        clearPendingFlag();
      }
      recoveryHandledRef.current = true;
    }

    startInit();
  }, [enabled, retryToken, internalToken, startInit]);

  const acceptConsent = useCallback(() => {
    writeConsent("accepted");
    setInternalToken((n) => n + 1); // re-run the effect, this time consent is accepted
  }, []);

  const declineConsent = useCallback(() => {
    writeConsent("declined");
    setStatus("idle");
    // Caller is responsible for flipping llm_mode to cloud.
  }, []);

  const acknowledgeRecovery = useCallback(
    (action: "retry" | "switchToCloud") => {
      clearPendingFlag();
      recoveryHandledRef.current = true;
      if (action === "switchToCloud") {
        setStatus("idle");
        // Caller is responsible for flipping llm_mode to cloud.
        return;
      }
      // Retry: re-run the effect, which will skip the recovery gate now.
      setInternalToken((n) => n + 1);
    },
    [],
  );

  const markStableInference = useCallback(() => {
    clearPendingFlag();
  }, []);

  return {
    status,
    progress,
    error,
    isReady: status === "ready",
    acceptConsent,
    declineConsent,
    acknowledgeRecovery,
    markStableInference,
  };
}
```

- [ ] **Step 3: Verify TypeScript**

Run: `cd web && npx tsc --noEmit`
Expected: errors in `NotesWorkspace.tsx` because it doesn't yet pass / consume the new fields. THIS IS EXPECTED. Tasks 8 and 9 fix it.

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run`
Expected: all existing tests pass. NotesWorkspace tests already mock the hook lightly enough that the new return fields don't break them.

If any test breaks because it `vi.mock`s `useEdgeLLM` and asserts the return shape, update that mock to include the four new function fields as `vi.fn()`.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/hooks/useEdgeLLM.ts
git commit -m "$(cat <<'EOF'
useEdgeLLM: consent + crash gating

Hook now reads neuronote:edge-consent and neuronote:edge-init-pending
on every effect run. While consent is absent or declined, status stays
'awaiting-consent'. While a recent pending flag exists, status stays
'awaiting-recovery'. Imperative methods exposed for the dialog and
banner to drive transitions.

The crash flag is written immediately before initializeEngine and
cleared by the caller via markStableInference after the first
successful inference.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: EdgeConsentDialog component

**Files:**
- Create: `web/src/components/llm/EdgeConsentDialog.tsx`
- Create: `web/src/components/llm/__tests__/EdgeConsentDialog.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `web/src/components/llm/__tests__/EdgeConsentDialog.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { EdgeConsentDialog } from "../EdgeConsentDialog";

describe("EdgeConsentDialog", () => {
  it("does not render when isOpen=false", () => {
    render(
      <EdgeConsentDialog
        isOpen={false}
        onAccept={vi.fn()}
        onDecline={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Choose how AI runs/i)).not.toBeInTheDocument();
  });

  it("renders both options when isOpen=true", () => {
    render(
      <EdgeConsentDialog
        isOpen
        onAccept={vi.fn()}
        onDecline={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText(/Choose how AI runs/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use Edge AI/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use Cloud AI/i })).toBeInTheDocument();
  });

  it("calls onAccept when 'Use Edge AI' is clicked", () => {
    const onAccept = vi.fn();
    render(
      <EdgeConsentDialog
        isOpen
        onAccept={onAccept}
        onDecline={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Use Edge AI/i }));
    expect(onAccept).toHaveBeenCalledTimes(1);
  });

  it("calls onDecline when 'Use Cloud AI' is clicked", () => {
    const onDecline = vi.fn();
    render(
      <EdgeConsentDialog
        isOpen
        onAccept={vi.fn()}
        onDecline={onDecline}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Use Cloud AI/i }));
    expect(onDecline).toHaveBeenCalledTimes(1);
  });

  it("calls onDismiss when Escape is pressed", () => {
    const onDismiss = vi.fn();
    render(
      <EdgeConsentDialog
        isOpen
        onAccept={vi.fn()}
        onDecline={vi.fn()}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd web && npx vitest run src/components/llm/__tests__/EdgeConsentDialog.test.tsx`
Expected: FAIL — `Cannot find module '../EdgeConsentDialog'`.

- [ ] **Step 3: Implement**

Create `web/src/components/llm/EdgeConsentDialog.tsx`:

```typescript
"use client";

/**
 * Modal asking the user to choose between edge AI (in-browser) and
 * cloud AI (server with their API key). Shown once per browser, the
 * first time edge mode is selected, before any model download starts.
 *
 * Accepts via the "Use Edge AI" button. Declines via "Use Cloud AI"
 * (caller is responsible for flipping `llm_mode` to "cloud").
 * Closing without choosing (Esc) leaves consent absent — the dialog
 * re-shows on next reload.
 */

import React, { useEffect } from "react";

interface EdgeConsentDialogProps {
  isOpen: boolean;
  onAccept: () => void;
  onDecline: () => void;
  onDismiss: () => void;
}

export function EdgeConsentDialog({
  isOpen,
  onAccept,
  onDecline,
  onDismiss,
}: EdgeConsentDialogProps) {
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onDismiss]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="edge-consent-title"
      onClick={onDismiss}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--panel-bg)",
          border: "1px solid var(--panel-border)",
          borderRadius: "12px",
          padding: "2rem",
          maxWidth: "480px",
          width: "100%",
          boxShadow: "var(--shadow-panel)",
        }}
      >
        <h2
          id="edge-consent-title"
          style={{
            margin: "0 0 0.5rem",
            fontSize: "1.25rem",
            fontWeight: 700,
            color: "var(--text-strong)",
          }}
        >
          Choose how AI runs
        </h2>
        <p
          style={{
            margin: "0 0 1.25rem",
            fontSize: "var(--text-sm)",
            color: "var(--text-muted)",
          }}
        >
          You can change this later in settings.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: "1rem", marginBottom: "1.5rem" }}>
          <div
            style={{
              padding: "0.75rem 1rem",
              border: "1px solid var(--panel-border)",
              borderRadius: "8px",
              background: "var(--workspace-surface)",
            }}
          >
            <strong style={{ color: "var(--text-strong)", fontSize: "var(--text-base)" }}>
              🖥️ Edge AI (in your browser)
            </strong>
            <p
              style={{
                margin: "0.25rem 0 0",
                fontSize: "var(--text-sm)",
                color: "var(--text-muted)",
                lineHeight: 1.5,
              }}
            >
              Your notes never leave this device. Uses ~2GB of memory while you
              work. Processing takes ~30s for long notes.
            </p>
          </div>

          <div
            style={{
              padding: "0.75rem 1rem",
              border: "1px solid var(--panel-border)",
              borderRadius: "8px",
              background: "var(--workspace-surface)",
            }}
          >
            <strong style={{ color: "var(--text-strong)", fontSize: "var(--text-base)" }}>
              ☁️ Cloud AI (your API key)
            </strong>
            <p
              style={{
                margin: "0.25rem 0 0",
                fontSize: "var(--text-sm)",
                color: "var(--text-muted)",
                lineHeight: 1.5,
              }}
            >
              Faster. Works on any device. Requires an API key from
              OpenAI/Anthropic.
            </p>
          </div>
        </div>

        <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={onDecline}
            style={{
              padding: "0.5rem 1rem",
              fontSize: "var(--text-sm)",
              fontWeight: 600,
              color: "var(--text-strong)",
              background: "transparent",
              border: "1px solid var(--panel-border)",
              borderRadius: "6px",
              cursor: "pointer",
            }}
          >
            Use Cloud AI
          </button>
          <button
            type="button"
            onClick={onAccept}
            style={{
              padding: "0.5rem 1rem",
              fontSize: "var(--text-sm)",
              fontWeight: 600,
              color: "#fff",
              background: "var(--accent)",
              border: "1px solid var(--accent)",
              borderRadius: "6px",
              cursor: "pointer",
            }}
          >
            Use Edge AI
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/components/llm/__tests__/EdgeConsentDialog.test.tsx`
Expected: 5/5 pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/llm/EdgeConsentDialog.tsx web/src/components/llm/__tests__/EdgeConsentDialog.test.tsx
git commit -m "$(cat <<'EOF'
llm: EdgeConsentDialog modal

Two-option modal asking the user to pick edge or cloud AI before any
model download begins. Marketing-friendly framing (no warnings, just
trade-offs). Esc and backdrop click trigger onDismiss; explicit
button clicks trigger onAccept / onDecline.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: EdgeCrashBanner component

**Files:**
- Create: `web/src/components/llm/EdgeCrashBanner.tsx`
- Create: `web/src/components/llm/__tests__/EdgeCrashBanner.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `web/src/components/llm/__tests__/EdgeCrashBanner.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { EdgeCrashBanner } from "../EdgeCrashBanner";

describe("EdgeCrashBanner", () => {
  it("does not render when isOpen=false", () => {
    render(<EdgeCrashBanner isOpen={false} onAcknowledge={vi.fn()} />);
    expect(screen.queryByText(/didn't finish loading/i)).not.toBeInTheDocument();
  });

  it("renders all three actions when isOpen=true", () => {
    render(<EdgeCrashBanner isOpen onAcknowledge={vi.fn()} />);
    expect(screen.getByText(/didn't finish loading/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Switch to Cloud AI/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Try Edge AI again/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Dismiss/i })).toBeInTheDocument();
  });

  it("calls onAcknowledge('switchToCloud') when 'Switch to Cloud AI' clicked", () => {
    const onAcknowledge = vi.fn();
    render(<EdgeCrashBanner isOpen onAcknowledge={onAcknowledge} />);
    fireEvent.click(screen.getByRole("button", { name: /Switch to Cloud AI/i }));
    expect(onAcknowledge).toHaveBeenCalledWith("switchToCloud");
  });

  it("calls onAcknowledge('retry') when 'Try Edge AI again' clicked", () => {
    const onAcknowledge = vi.fn();
    render(<EdgeCrashBanner isOpen onAcknowledge={onAcknowledge} />);
    fireEvent.click(screen.getByRole("button", { name: /Try Edge AI again/i }));
    expect(onAcknowledge).toHaveBeenCalledWith("retry");
  });

  it("calls onAcknowledge('retry') when Dismiss (×) clicked", () => {
    const onAcknowledge = vi.fn();
    render(<EdgeCrashBanner isOpen onAcknowledge={onAcknowledge} />);
    fireEvent.click(screen.getByRole("button", { name: /Dismiss/i }));
    expect(onAcknowledge).toHaveBeenCalledWith("retry");
  });
});
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd web && npx vitest run src/components/llm/__tests__/EdgeCrashBanner.test.tsx`
Expected: FAIL — `Cannot find module '../EdgeCrashBanner'`.

- [ ] **Step 3: Implement**

Create `web/src/components/llm/EdgeCrashBanner.tsx`:

```typescript
"use client";

/**
 * Banner shown when a previous edge-mode session set the
 * 'edge-init-pending' flag and never cleared it (i.e. the tab was
 * killed mid-load). Lets the user switch to cloud mode in one click,
 * retry edge, or dismiss.
 *
 * Rendered above ModelDownloadProgress in NotesWorkspace.tsx.
 */

import React from "react";

interface EdgeCrashBannerProps {
  isOpen: boolean;
  onAcknowledge: (action: "retry" | "switchToCloud") => void;
}

export function EdgeCrashBanner({ isOpen, onAcknowledge }: EdgeCrashBannerProps) {
  if (!isOpen) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 50,
        background: "color-mix(in srgb, var(--danger) 14%, transparent)",
        borderBottom: "1px solid color-mix(in srgb, var(--danger) 35%, transparent)",
        padding: "10px 20px",
        display: "flex",
        alignItems: "center",
        gap: "12px",
        fontSize: "var(--text-sm)",
      }}
    >
      <span style={{ flex: 1, color: "var(--text-strong)" }}>
        <strong>⚠ Edge AI didn't finish loading last time.</strong>{" "}
        This usually means the device ran out of memory.
      </span>
      <button
        type="button"
        onClick={() => onAcknowledge("switchToCloud")}
        style={{
          padding: "0.3rem 0.75rem",
          fontSize: "var(--text-xs)",
          fontWeight: 600,
          color: "#fff",
          background: "var(--accent)",
          border: "1px solid var(--accent)",
          borderRadius: "4px",
          cursor: "pointer",
        }}
      >
        Switch to Cloud AI
      </button>
      <button
        type="button"
        onClick={() => onAcknowledge("retry")}
        style={{
          padding: "0.3rem 0.75rem",
          fontSize: "var(--text-xs)",
          fontWeight: 600,
          color: "var(--text-strong)",
          background: "transparent",
          border: "1px solid var(--panel-border)",
          borderRadius: "4px",
          cursor: "pointer",
        }}
      >
        Try Edge AI again
      </button>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => onAcknowledge("retry")}
        style={{
          padding: "0.2rem 0.5rem",
          fontSize: "var(--text-base)",
          color: "var(--text-muted)",
          background: "transparent",
          border: "none",
          cursor: "pointer",
        }}
      >
        ×
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/components/llm/__tests__/EdgeCrashBanner.test.tsx`
Expected: 5/5 pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/llm/EdgeCrashBanner.tsx web/src/components/llm/__tests__/EdgeCrashBanner.test.tsx
git commit -m "$(cat <<'EOF'
llm: EdgeCrashBanner

Banner offering 'Switch to Cloud AI', 'Try Edge AI again', or × to
dismiss. Both Try Again and Dismiss send the same action — the
caller clears the pending flag and re-runs the engine init effect.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: LiveConceptsPreview component

**Files:**
- Create: `web/src/components/llm/LiveConceptsPreview.tsx`
- Create: `web/src/components/llm/__tests__/LiveConceptsPreview.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `web/src/components/llm/__tests__/LiveConceptsPreview.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { LiveConceptsPreview } from "../LiveConceptsPreview";

describe("LiveConceptsPreview", () => {
  it("renders nothing when concepts is empty", () => {
    const { container } = render(
      <LiveConceptsPreview concepts={[]} isProcessing />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows the count when concepts is non-empty", () => {
    render(
      <LiveConceptsPreview concepts={["a", "b", "c"]} isProcessing />,
    );
    expect(screen.getByRole("button")).toHaveTextContent("3 concepts found");
  });

  it("popover is closed by default — concepts not visible", () => {
    render(
      <LiveConceptsPreview concepts={["alpha", "beta"]} isProcessing />,
    );
    expect(screen.queryByText("alpha")).not.toBeInTheDocument();
    expect(screen.queryByText("beta")).not.toBeInTheDocument();
  });

  it("clicking the pill toggles the popover", () => {
    render(
      <LiveConceptsPreview concepts={["alpha", "beta"]} isProcessing />,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button"));
    expect(screen.queryByText("alpha")).not.toBeInTheDocument();
  });

  it("renders concepts in insertion order", () => {
    render(
      <LiveConceptsPreview concepts={["zeta", "alpha", "mu"]} isProcessing />,
    );
    fireEvent.click(screen.getByRole("button"));
    const items = screen.getAllByRole("listitem").map((el) => el.textContent);
    expect(items).toEqual(["zeta", "alpha", "mu"]);
  });
});
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd web && npx vitest run src/components/llm/__tests__/LiveConceptsPreview.test.tsx`
Expected: FAIL — `Cannot find module '../LiveConceptsPreview'`.

- [ ] **Step 3: Implement**

Create `web/src/components/llm/LiveConceptsPreview.tsx`:

```typescript
"use client";

/**
 * Toolbar pill showing how many concepts have been streamed in so far,
 * with a click-to-expand popover listing them in insertion order.
 *
 * Pure presentation: parent passes `concepts` (already-deduped by the
 * parent's accumulator) and `isProcessing` (controls icon).
 *
 * Renders nothing while concepts is empty so the toolbar layout
 * doesn't shift on the first chunk.
 */

import React, { useState } from "react";

interface LiveConceptsPreviewProps {
  concepts: string[];
  /** Whether the pipeline is still running. Drives the icon (spinner vs check). */
  isProcessing: boolean;
}

export function LiveConceptsPreview({
  concepts,
  isProcessing,
}: LiveConceptsPreviewProps) {
  const [open, setOpen] = useState(false);

  if (concepts.length === 0) return null;

  const icon = isProcessing ? "⚙" : "✓";
  const label = `${concepts.length} concept${concepts.length === 1 ? "" : "s"} found`;

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          padding: "0.2rem 0.55rem",
          borderRadius: "999px",
          border: "1px solid var(--panel-border)",
          background: "var(--accent-soft)",
          color: "var(--accent-ink)",
          fontSize: "var(--text-xs)",
          fontWeight: 500,
          cursor: "pointer",
          display: "inline-flex",
          alignItems: "center",
          gap: "6px",
        }}
      >
        <span aria-hidden="true">{icon}</span>
        {label}
        <span aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div
          role="region"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            right: 0,
            zIndex: 100,
            minWidth: "200px",
            maxWidth: "320px",
            maxHeight: "240px",
            overflowY: "auto",
            background: "var(--panel-bg)",
            border: "1px solid var(--panel-border)",
            borderRadius: "6px",
            boxShadow: "var(--shadow-panel)",
            padding: "0.5rem",
          }}
        >
          <ul
            style={{
              margin: 0,
              padding: 0,
              listStyle: "none",
              fontSize: "var(--text-xs)",
              color: "var(--text-strong)",
            }}
          >
            {concepts.map((c, i) => (
              <li
                key={`${i}:${c}`}
                style={{
                  padding: "0.2rem 0.4rem",
                  borderBottom:
                    i < concepts.length - 1
                      ? "1px solid var(--panel-border)"
                      : "none",
                }}
              >
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/components/llm/__tests__/LiveConceptsPreview.test.tsx`
Expected: 5/5 pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/llm/LiveConceptsPreview.tsx web/src/components/llm/__tests__/LiveConceptsPreview.test.tsx
git commit -m "$(cat <<'EOF'
llm: LiveConceptsPreview pill + popover

Pure presentation component. Parent accumulates the streaming
concept list; this just renders the count in a clickable pill and
expands an in-order list on click. Hides itself when concepts is
empty so the toolbar layout doesn't shift on the first chunk.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Add onChunkResult callback to runEdgeProcessing

**Files:**
- Modify: `web/src/lib/orchestration/edge-processing.ts`

- [ ] **Step 1: Read current file**

Run: `grep -n "onProgress\|EdgeProcessingRequest\|extractFromChunk" web/src/lib/orchestration/edge-processing.ts`

Look at the chunk-loop body and the request-shape interface.

- [ ] **Step 2: Add the new callback to the request interface**

Find the `EdgeProcessingRequest` interface (currently has `onProgress`). Add:

```typescript
  /** Optional callback fired with new concepts after each chunk's LLM call. */
  onChunkResult?: (chunkConcepts: string[]) => void;
```

So the interface looks like:

```typescript
export interface EdgeProcessingRequest {
  baseUrl: string;
  noteId: string;
  noteTitle: string;
  contentText: string;
  contentHash: string;
  /** Optional progress callback: (chunksDone, totalChunks) -> void */
  onProgress?: (done: number, total: number) => void;
  /** Optional callback fired with new concepts after each chunk's LLM call. */
  onChunkResult?: (chunkConcepts: string[]) => void;
}
```

- [ ] **Step 3: Wire the callback in the chunk loop**

Find the block inside `for (const chunk of chunks)` where `result` is assigned from `await extractFromChunk(...)`. Immediately after that block successfully reads `result.keep`, before the loop iterates, fire the callback.

Locate this existing block:

```typescript
      for (const idx of result.keep) {
        const text = candidates[idx];
        if (!text) continue;
        allConcepts.push({
          text,
          confidence: 0.9,
          sources: [chunk.index],
        });
      }
```

Replace it with:

```typescript
      const chunkConcepts: string[] = [];
      for (const idx of result.keep) {
        const text = candidates[idx];
        if (!text) continue;
        allConcepts.push({
          text,
          confidence: 0.9,
          sources: [chunk.index],
        });
        chunkConcepts.push(text);
      }
      request.onChunkResult?.(chunkConcepts);
```

- [ ] **Step 4: Verify TypeScript**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Run all tests**

Run: `cd web && npx vitest run`
Expected: all tests still pass. The new callback is optional — no caller needs updating to keep working.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/orchestration/edge-processing.ts
git commit -m "$(cat <<'EOF'
edge-processing: stream concept names per-chunk via onChunkResult

After each chunk's LLM call, fire the optional onChunkResult callback
with just the canonical surface forms (mapped from candidates[idx])
of the kept concepts. Pre-dedup so the user sees immediate progress;
the existing reducer still produces the final clean set.

Optional callback — existing callers continue to work.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Wire progress + live concepts into NoteEditor

**Files:**
- Modify: `web/src/components/editor/NoteEditor.tsx`

- [ ] **Step 1: Add the new state slots**

In `NoteEditor.tsx`, find the existing line:

```typescript
  const [processStatus, setProcessStatus] = useState<ProcessStatus>("idle");
```

Immediately after it, add:

```typescript
  const [processProgress, setProcessProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);
  const [liveConcepts, setLiveConcepts] = useState<string[]>([]);
```

- [ ] **Step 2: Accept the new prop for hook handle**

Find the existing props interface for `NoteEditor` (search for `interface NoteEditorProps`). It currently has `llmMode` and `edgeReady`. Add:

```typescript
  edgeMarkStableInference?: () => void;
```

The destructuring line near the top of the function — add `edgeMarkStableInference` to it.

- [ ] **Step 3: Reset state and wire callbacks in startProcessing (edge branch)**

Find the existing edge branch in `startProcessing`. The current call to `runEdgeProcessing` is:

```typescript
        const result = await runEdgeProcessing({
          baseUrl,
          noteId,
          noteTitle: snapshot.noteTitle.trim() || "Untitled",
          contentText: snapshot.plainText,
          contentHash,
          onProgress: (done, total) => {
            console.info(`[edge-llm] chunk ${done}/${total}`);
          },
        });
```

Replace with:

```typescript
        setProcessProgress(null);
        setLiveConcepts([]);
        const result = await runEdgeProcessing({
          baseUrl,
          noteId,
          noteTitle: snapshot.noteTitle.trim() || "Untitled",
          contentText: snapshot.plainText,
          contentHash,
          onProgress: (done, total) => {
            console.info(`[edge-llm] chunk ${done}/${total}`);
            setProcessProgress({ done, total });
          },
          onChunkResult: (concepts) => {
            setLiveConcepts((prev) => {
              const seen = new Set(prev.map((c) => c.toLowerCase()));
              const merged = [...prev];
              for (const c of concepts) {
                const key = c.toLowerCase();
                if (!seen.has(key)) {
                  merged.push(c);
                  seen.add(key);
                }
              }
              // Cap at 50 — popover unhelpful beyond that.
              return merged.length > 50 ? merged.slice(-50) : merged;
            });
          },
        });
```

- [ ] **Step 4: Clear progress + call markStableInference on success**

Immediately after the `if (result.status === "completed") { ... }` block in the edge branch, before the closing `}` of the try, add:

```typescript
        setProcessProgress(null);
        if (result.status === "completed") {
          edgeMarkStableInference?.();
        }
```

(If the existing code already includes a final `setProcessProgress(null)` — keep one copy. The point is: progress clears in completed and failed paths.)

Inside the `catch` of the edge branch, also add:

```typescript
        setProcessProgress(null);
```

- [ ] **Step 5: Pass new state to EditorToolbar**

Find the existing JSX where `<EditorToolbar ... />` is rendered. Add two new props:

```typescript
          <EditorToolbar
            dirty={dirty}
            saveStatus={saveStatus}
            processStatus={processStatus}
            processProgress={processProgress}
            liveConcepts={liveConcepts}
          />
```

- [ ] **Step 6: Verify TypeScript**

Run: `cd web && npx tsc --noEmit`
Expected: errors in `EditorToolbar.tsx` (it doesn't yet accept the new props) AND in `NotesWorkspace.tsx` (it doesn't pass `edgeMarkStableInference`). Tasks 9 and 10 fix those.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/editor/NoteEditor.tsx
git commit -m "$(cat <<'EOF'
NoteEditor: wire per-chunk progress + streaming concepts

Two new state slots (processProgress, liveConcepts) feed the
toolbar. Edge processing's onProgress callback now updates UI
state alongside the existing console log. New onChunkResult
appends new concepts (case-insensitive dedup, capped at 50) for
the LiveConceptsPreview pill.

After a successful run, calls the new edgeMarkStableInference
prop to clear the crash flag. Progress state resets to null on
completion or failure.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Forward props through EditorToolbar + extend StatusBadge

**Files:**
- Modify: `web/src/components/editor/EditorToolbar.tsx`
- Modify: `web/src/components/editor/StatusBadge.tsx`

- [ ] **Step 1: Replace EditorToolbar**

Overwrite `web/src/components/editor/EditorToolbar.tsx`:

```typescript
import type { ProcessStatus, SaveStatus } from "../../lib/state/note-store";
import { SaveStatusBadge, ProcessStatusBadge } from "./StatusBadge";
import { LiveConceptsPreview } from "../llm/LiveConceptsPreview";

interface EditorToolbarProps {
  dirty: boolean;
  saveStatus: SaveStatus;
  processStatus: ProcessStatus;
  processProgress?: { done: number; total: number } | null;
  liveConcepts?: string[];
}

export function EditorToolbar({
  dirty,
  saveStatus,
  processStatus,
  processProgress,
  liveConcepts,
}: EditorToolbarProps) {
  const showLive =
    (liveConcepts?.length ?? 0) > 0 &&
    (processStatus === "running" || processStatus === "completed");
  return (
    <div className="editor-toolbar" data-testid="editor-toolbar">
      <div data-testid="save-status">
        <SaveStatusBadge status={saveStatus} />
      </div>
      <div data-testid="process-status" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <ProcessStatusBadge status={processStatus} progress={processProgress ?? null} />
        {showLive && (
          <LiveConceptsPreview
            concepts={liveConcepts ?? []}
            isProcessing={processStatus === "running"}
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Extend ProcessStatusBadge in StatusBadge.tsx**

In `web/src/components/editor/StatusBadge.tsx`, find the existing `ProcessStatusBadge` function. Replace ONLY that function (keep `SaveStatusBadge` and the configs unchanged):

```typescript
export function ProcessStatusBadge({
  status,
  progress,
}: {
  status: ProcessStatus;
  progress?: { done: number; total: number } | null;
}) {
  const config = PROCESS_STATUS_CONFIG[status];
  if (!config.label) return null;

  const label =
    status === "running" && progress && progress.total > 1
      ? `${config.label} ${progress.done}/${progress.total}`
      : config.label;

  return (
    <span className={`status-badge ${config.className}`} role="status">
      <span className="status-icon" aria-hidden="true">
        {config.icon}
      </span>
      <span className="status-label">{label}</span>
    </span>
  );
}
```

- [ ] **Step 3: Verify TypeScript**

Run: `cd web && npx tsc --noEmit`
Expected: errors only in `NotesWorkspace.tsx` (still doesn't pass `edgeMarkStableInference` to NoteEditor). Task 10 fixes it.

- [ ] **Step 4: Run all tests**

Run: `cd web && npx vitest run`
Expected: all tests pass. NoteEditor and NotesWorkspace tests should be unaffected — the new toolbar props are optional with safe defaults.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/editor/EditorToolbar.tsx web/src/components/editor/StatusBadge.tsx
git commit -m "$(cat <<'EOF'
toolbar: render LiveConceptsPreview + per-chunk progress

EditorToolbar accepts optional processProgress and liveConcepts;
forwards progress to ProcessStatusBadge (which appends 'N/M' to
the label when running with multi-chunk progress) and renders the
LiveConceptsPreview pill next to it.

Both new props default to safe absent values so cloud mode and
non-edge callers see no behavior change.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Wire dialog + banner into NotesWorkspace

**Files:**
- Modify: `web/src/components/workspace/NotesWorkspace.tsx`

- [ ] **Step 1: Find the existing edge-llm wiring**

Run: `grep -n "useEdgeLLM\|edgeMode\|edge\\.\\|WebGPUCheck\|ModelDownloadProgress\|<NoteEditor" web/src/components/workspace/NotesWorkspace.tsx`

Identify:
- Where `edge = useEdgeLLM(...)` is called
- Where `<WebGPUCheck>` is rendered
- Where `<ModelDownloadProgress>` is rendered
- Where `<NoteEditor>` is rendered with its props

- [ ] **Step 2: Import the new components and the api-client**

At the top of `NotesWorkspace.tsx`, add (alongside existing imports from these directories):

```typescript
import { EdgeConsentDialog } from "../llm/EdgeConsentDialog";
import { EdgeCrashBanner } from "../llm/EdgeCrashBanner";
import { updatePreferences } from "../../lib/api-client";
```

If `updatePreferences` is already imported from `../../lib/api-client`, skip that import.

- [ ] **Step 3: Add a handler to flip llm_mode to cloud**

Inside the component body (anywhere reasonable, e.g. just after the `useEdgeLLM` call), add:

```typescript
  const switchToCloud = useCallback(async () => {
    try {
      await updatePreferences({ llm_mode: "cloud" });
      void prefs.reload();
    } catch (err) {
      console.error("[NotesWorkspace] switchToCloud failed", err);
    }
  }, [prefs]);
```

If `useCallback` is not yet imported from `react`, add it to the existing react import.

If `prefs` is not the variable name of the `usePreferences()` return value in this file, replace with the actual name.

- [ ] **Step 4: Render the consent dialog**

Just before the existing `<WebGPUCheck>` JSX, add:

```typescript
      <EdgeConsentDialog
        isOpen={edgeMode && edge.status === "awaiting-consent"}
        onAccept={edge.acceptConsent}
        onDecline={() => {
          edge.declineConsent();
          void switchToCloud();
        }}
        onDismiss={() => {
          // Leave consent absent; the dialog re-shows on reload.
          // No state change needed because the hook's status remains
          // 'awaiting-consent' until the user makes a choice.
        }}
      />
```

`edgeMode` is the existing boolean derived from `prefs?.llm_mode === "edge"` — re-use the same expression you already have in this file. If no such variable exists, add:

```typescript
  const edgeMode = prefs?.llm_mode === "edge";
```

- [ ] **Step 5: Render the crash banner**

Just before the existing `<ModelDownloadProgress>` JSX, add:

```typescript
      <EdgeCrashBanner
        isOpen={edgeMode && edge.status === "awaiting-recovery"}
        onAcknowledge={(action) => {
          edge.acknowledgeRecovery(action);
          if (action === "switchToCloud") {
            void switchToCloud();
          }
        }}
      />
```

- [ ] **Step 6: Pass markStableInference into NoteEditor**

Find the `<NoteEditor ... />` render. Add the new prop:

```typescript
        edgeMarkStableInference={edge.markStableInference}
```

- [ ] **Step 7: Verify TypeScript**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 8: Run all tests**

Run: `cd web && npx vitest run`
Expected: 178 + 13 (persistence) + 5 (consent dialog) + 5 (crash banner) + 5 (live preview) = 206 tests pass.

If `NotesWorkspace.test.tsx` fails because its mock of `useEdgeLLM` doesn't include the new functions, update the mock to add:

```typescript
acceptConsent: vi.fn(),
declineConsent: vi.fn(),
acknowledgeRecovery: vi.fn(),
markStableInference: vi.fn(),
```

If `updatePreferences` is freshly imported in the workspace and the workspace test mock doesn't expose it, update the mock similarly.

- [ ] **Step 9: Commit**

```bash
git add web/src/components/workspace/NotesWorkspace.tsx
git commit -m "$(cat <<'EOF'
workspace: render EdgeConsentDialog + EdgeCrashBanner

Consent dialog gates the engine when edge mode is selected with
no prior consent. Decline path flips llm_mode to cloud via
updatePreferences. Crash banner offers retry or cloud switch.
NoteEditor now receives markStableInference so it can clear the
crash flag after the first successful inference.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: End-to-end verification against the running stack

**Files:** none modified.

- [ ] **Step 1: Restart the web container**

```bash
docker compose -f infra/docker-compose.yml restart web
sleep 15
```

The API doesn't need a restart — only frontend changed.

- [ ] **Step 2: Reset the browser state for a clean test**

In the browser DevTools Console at http://localhost:3000:

```javascript
localStorage.removeItem("neuronote:edge-consent");
localStorage.removeItem("neuronote:edge-init-pending");
location.reload();
```

Then log in if needed.

- [ ] **Step 3: Verify the consent dialog appears**

In settings, ensure llm_mode is "edge". Open the workspace.

Expected:
- Consent dialog appears with "Choose how AI runs" title
- Two cards (Edge AI / Cloud AI) and two buttons
- No model download starts in DevTools Network panel

- [ ] **Step 4: Verify the Decline path**

Click "Use Cloud AI".

Expected:
- Dialog dismisses
- DevTools: `localStorage.getItem("neuronote:edge-consent")` returns `"declined"`
- DevTools Network: a PUT to /v1/preferences fires with `{"llm_mode":"cloud"}`
- Workspace settings now show cloud mode

- [ ] **Step 5: Verify the Accept path**

Switch back to edge mode in settings (this re-triggers the dialog because consent is "declined"). Click "Use Edge AI".

Expected:
- `localStorage.getItem("neuronote:edge-consent")` is now `"accepted"`
- `localStorage.getItem("neuronote:edge-init-pending")` is set to a JSON object with `startedAt`
- Model download progress banner appears

- [ ] **Step 6: Verify the markStableInference clears the flag**

Wait for the model to load (or use existing cached model). Edit a note and wait for processing to complete.

Expected:
- Console shows `[edge-llm] chunk N/M` logs
- After processing completes, `localStorage.getItem("neuronote:edge-init-pending")` returns `null`

- [ ] **Step 7: Simulate a crash and verify the banner**

In DevTools Console:

```javascript
localStorage.setItem(
  "neuronote:edge-init-pending",
  JSON.stringify({ startedAt: Date.now() }),
);
location.reload();
```

Expected:
- After page loads (and consent dialog does NOT re-appear because consent is still "accepted"), the EdgeCrashBanner is visible at the top of the workspace
- "Switch to Cloud AI" / "Try Edge AI again" / × buttons render

- [ ] **Step 8: Verify Try Again clears the flag**

Click "Try Edge AI again".

Expected:
- Banner dismisses
- `localStorage.getItem("neuronote:edge-init-pending")` is set to a fresh value (engine init started again)
- Model loading proceeds normally

- [ ] **Step 9: Verify per-chunk progress in the badge**

Edit a long note (e.g. one of the JS notes ~3000 chars). Watch the toolbar badge.

Expected:
- Badge cycles through "Processing 1/N", "Processing 2/N", ..., "Processing N/N"
- After completion: badge reads "Processing complete" (no fraction)

- [ ] **Step 10: Verify the LiveConceptsPreview pill**

While processing the same note, watch the toolbar.

Expected:
- After the first chunk's LLM call returns, a pill "X concepts found ▾" appears next to the badge
- The count grows as each subsequent chunk completes
- Clicking the pill expands a popover listing the concepts in insertion order
- After processing finishes, pill stays visible briefly with the final count

- [ ] **Step 11: No regression check on cloud mode**

Switch to cloud mode in settings. Edit a note.

Expected:
- No consent dialog (cloud doesn't go through edge gating)
- No live preview pill (cloud doesn't fire onChunkResult)
- Badge reads "Processing" without a fraction (cloud doesn't pass progress)

- [ ] **Step 12: No final commit needed**

Verification only. If any cosmetic cleanup surfaced, commit it as a separate small change. Otherwise the work is done.

---

## Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| `useEdgeLLM` consumers (NotesWorkspace, NotesWorkspace.test) don't include new return fields | Task 3 step 4 + Task 10 step 8 explicitly note updating the mocks. |
| `updatePreferences` failure leaves the user stuck in edge mode after declining | The decline path tries to flip; if it fails, the user can still use the engine (consent was declined but engine never inits — they're on the consent dialog forever). Acceptable: they can refresh and retry. Worth a follow-up retry-with-toast if it occurs in practice. |
| Crash flag lingers across multiple tabs | Acknowledged in spec. False-positive banner; one click to dismiss. |
| `LiveConceptsPreview` popover stays open while user navigates away | The `open` state is local; switching notes unmounts the toolbar and re-mounts fresh. No leak. |
| ModelStatus exhaustive switches break with new statuses | Audited: no consumer switches exhaustively on `ModelStatus`. Adding members is safe. |

## What this plan does NOT do (out of scope)

- A "Reset consent" button in `LLMSettings` (deferred per spec).
- Heartbeat-based crash detection (1-hour stale rule is the chosen mechanism).
- Showing rule-based candidates as a preview (the deferred "C" option from brainstorming).
- Showing relations live as they're discovered.
- Telemetry on banner accuracy.
