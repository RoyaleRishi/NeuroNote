# Edge Mode Consent + Progress Design

## Context

NeuroNote's edge AI mode runs Llama 3.2 3B in the browser via WebGPU. Two real problems are degrading user experience:

1. **OOM-induced reloads.** The model occupies ~2GB of VRAM plus worker thread memory. Browsers (and the OS) kill tabs that exceed memory budgets. Users see the page refresh without explanation. There is no `permission` API for memory; the kill is invisible to JavaScript when it happens.
2. **Slow processing feels broken.** The chunked map-reduce pipeline takes 30–60s for a long note (6 chunks × 5–10s each). The current UI shows a single "Processing" badge with no detail. The user has no signal that work is progressing, so it feels stuck.

Compute and model quality cannot improve without changing models or hardware. This spec tackles UX only:

- **Prevent surprise** with an up-front consent dialog before any download starts.
- **Recover gracefully** with a banner that detects the previous session crashed mid-load.
- **Make it look fast** by showing per-chunk progress in the badge and streaming concept names into a live preview pill as each chunk completes.

## Goals

- Users acknowledge the memory cost of edge mode before paying it.
- After a crash-induced reload, users get a clear path to switch to cloud mode in one click.
- The processing badge shows concrete progress (`Processing 3/6`) instead of an opaque spinner.
- Users see concepts being discovered in real time, building confidence the system is doing something.

## Non-goals

- Throttling network or memory consumption during the model download (browsers don't expose those APIs).
- Preventing the OS from killing the tab. We can only react after.
- Any change to cloud mode flow, server-side processing, or the streaming-edge-extraction pipeline itself.
- Any reset-consent UI in settings (deferred to a follow-up; users can clear site data if needed).

## Architecture

Two new state machines surface in the workspace UI, plus light enhancements to the existing process-status display:

| Concern | New persistence | New component |
|---|---|---|
| Up-front consent | `localStorage["neuronote:edge-consent"]` | `EdgeConsentDialog` |
| Crash detection | `localStorage["neuronote:edge-init-pending"]` | `EdgeCrashBanner` |
| Per-chunk progress | (in-memory state) | `ProcessStatusBadge` extended |
| Streaming concepts | (in-memory state) | `LiveConceptsPreview` |

`useEdgeLLM` becomes the orchestrator for consent and crash detection. `runEdgeProcessing` gains streaming callbacks. `NoteEditor` plumbs the new state through its existing toolbar.

No backend changes. No new dependencies.

### Data flow

1. User selects edge mode in settings → `useEdgeLLM(enabled=true)` runs.
2. Hook reads `neuronote:edge-consent` from localStorage:
   - **absent** → status becomes `awaiting-consent`. Workspace renders `EdgeConsentDialog`. Engine init blocks.
   - **declined** → workspace forces `llm_mode` to `"cloud"`. Engine never inits.
   - **accepted** → hook reads `neuronote:edge-init-pending`. If a recent timestamp is found, status becomes `awaiting-recovery`. Workspace renders `EdgeCrashBanner`. Otherwise normal init proceeds.
3. Engine init writes `edge-init-pending = { startedAt: Date.now() }` immediately before `initializeEngine()`.
4. Engine reaches `ready`. After the first successful inference completes, the pending flag is cleared.
5. `runEdgeProcessing` calls `onProgress(done, total)` and `onChunkResult(newConcepts)` after each chunk. `NoteEditor` updates `processProgress` and `liveConcepts` state.
6. `EditorToolbar` renders the badge ("Processing 3/6") and the live preview pill ("7 concepts found ▾").

## Components

### `EdgeConsentDialog`

A modal rendered from `NotesWorkspace.tsx`. Shown only when edge mode is selected and `edge-consent` is absent.

Content (marketing-friendly framing):

> **Choose how AI runs**
>
> 🖥️ **Edge AI (in your browser)** — Your notes never leave this device. Uses ~2GB of memory while you work. Processing takes ~30s for long notes.
>
> ☁️ **Cloud AI (your API key)** — Faster. Works on any device. Requires an API key from OpenAI/Anthropic.
>
> [ Use Cloud AI ] [ Use Edge AI ]

Behavior:

- "Use Edge AI" → set `edge-consent = "accepted"`, dismiss dialog, allow engine init.
- "Use Cloud AI" → set `edge-consent = "declined"`, call `updatePreferences({ llm_mode: "cloud" })`, dismiss dialog. Workspace is now in cloud mode; if the user later flips back to edge, the dialog re-appears.
- Dismiss-without-choice (Esc / backdrop click) leaves consent absent. Engine does not init. Dialog re-shows on next reload. This is intentional: avoids accidentally trapping the user with a choice they didn't make.

The dialog uses the existing modal styling (matches `WebGPUCheck` and `LLMSettings`). No new design tokens.

### `EdgeCrashBanner`

A persistent banner rendered above `ModelDownloadProgress` in `NotesWorkspace.tsx`. Shown only when `useEdgeLLM` reports `awaiting-recovery`.

Content:

> ⚠ Edge AI didn't finish loading last time. This usually means the device ran out of memory.
>
> [ Switch to Cloud AI ] [ Try Edge AI again ] [ × ]

Behavior:

- "Switch to Cloud AI" → call `updatePreferences({ llm_mode: "cloud" })`, clear `edge-init-pending`, dismiss banner.
- "Try Edge AI again" → clear `edge-init-pending`, dismiss banner, allow engine init to start.
- "×" close → same as Try Again (clears flag, allows init). The user explicitly dismissed; default to letting them keep going.

### `useEdgeLLM` (extended)

The hook gains two new states and three new responsibilities.

New `ModelStatus` values:

```typescript
type ModelStatus =
  | "idle"
  | "awaiting-consent"   // NEW
  | "awaiting-recovery"  // NEW
  | "downloading"
  | "ready"
  | "error"
  | "unsupported";
```

New responsibilities:

1. **Consent gating.** On mount with `enabled=true`, check `edge-consent`:
   - **absent** → `awaiting-consent`. Show dialog.
   - **declined** → `awaiting-consent`. Show dialog. (User explicitly picked edge again; re-prompt rather than silently ignore.)
   - **accepted** → proceed to crash check.
2. **Crash detection.** Once consent is accepted, check `edge-init-pending`. If `startedAt` is within the last hour → `awaiting-recovery`. If older → silently clear and proceed.
3. **Crash flag lifecycle.** Set `edge-init-pending` immediately before `initializeEngine()`. Clear it after the first successful inference (signaled by the orchestrator — see below).

Stale-flag rule: `startedAt > 1 hour old` is treated as "user walked away last time, not a crash". This is a heuristic; tuning may follow if the rate of false positives is too high.

The hook exposes two new functions consumers can call:

```typescript
acceptConsent(): void;     // accepted, dismiss dialog
declineConsent(): void;    // sets cloud mode, dismiss dialog
acknowledgeRecovery(): void; // dismiss banner, retry edge
markStableInference(): void; // called by NoteEditor after first successful run
```

`markStableInference` is the signal that clears the crash flag. It must be called from the place that knows an inference actually completed — `NoteEditor` after `runEdgeProcessing` returns `status: "completed"`.

### `runEdgeProcessing` (extended)

Two callbacks added to `EdgeProcessingRequest`:

```typescript
interface EdgeProcessingRequest {
  // ...existing fields...
  onProgress?: (done: number, total: number) => void;          // already exists
  onChunkResult?: (chunkConcepts: string[]) => void;           // NEW
}
```

Wiring inside the chunk loop, after `extractFromChunk` returns successfully:

```typescript
const chunkConcepts = result.keep
  .map((idx) => candidates[idx])
  .filter((s): s is string => Boolean(s));
request.onChunkResult?.(chunkConcepts);
```

Pre-dedup is intentional: the user sees immediate progress, even if the same concept appears in two chunks. The reducer (`canonicalizeConcepts`) still produces the final clean set before submit.

### `NoteEditor` state additions

```typescript
const [processProgress, setProcessProgress] = useState<{ done: number; total: number } | null>(null);
const [liveConcepts, setLiveConcepts] = useState<string[]>([]);
```

In the edge branch of `startProcessing`:

```typescript
setProcessProgress(null);
setLiveConcepts([]);

const result = await runEdgeProcessing({
  baseUrl, noteId, noteTitle, contentText, contentHash,
  onProgress: (done, total) => setProcessProgress({ done, total }),
  onChunkResult: (concepts) => {
    setLiveConcepts((prev) => {
      const seen = new Set(prev.map((c) => c.toLowerCase()));
      const merged = [...prev];
      for (const c of concepts) {
        if (!seen.has(c.toLowerCase())) {
          merged.push(c);
          seen.add(c.toLowerCase());
        }
      }
      return merged;
    });
  },
});

if (result.status === "completed") {
  // ...existing setExtractionSummary call...
  edgeLLM.markStableInference();  // clears crash flag
}

setProcessProgress(null);
// liveConcepts left in place briefly so user sees the final list, then cleared
// when status returns to idle (existing flow).
```

### `ProcessStatusBadge` (extended)

Accepts an optional `progress` prop:

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
      <span className="status-icon" aria-hidden="true">{config.icon}</span>
      <span className="status-label">{label}</span>
    </span>
  );
}
```

Cloud mode never passes `progress`, so the badge reads `"Processing"` as today. Edge mode for a single-chunk note (`total === 1`) also skips the suffix to avoid noise.

### `LiveConceptsPreview` (new)

A controlled disclosure component: a button showing the count, with a popover listing the concepts.

```typescript
interface LiveConceptsPreviewProps {
  concepts: string[];
  isProcessing: boolean;  // controls the icon: spinner vs check
}
```

Behavior:
- If `concepts.length === 0` → render nothing.
- If `concepts.length > 0` → render a pill: `"{n} concepts found ▾"`. While `isProcessing=true`, show the spinner glyph; otherwise a check.
- Click → expand a popover listing the concepts in insertion order. Click outside → collapse.

This component is pure presentation. It owns its own open/closed state. It does not subscribe to any global state.

Placement: in `EditorToolbar`, immediately to the right of `ProcessStatusBadge`.

## Storage keys reference

| Key | Type | Lifetime | Set by | Cleared by |
|---|---|---|---|---|
| `neuronote:edge-consent` | localStorage | Forever (until user clears site data) | `EdgeConsentDialog` Accept/Decline buttons | (no automated clear) |
| `neuronote:edge-init-pending` | localStorage | From engine init start to first successful inference, or until next page load detects it as stale | `useEdgeLLM` before calling `initializeEngine` | `markStableInference()`, banner buttons, or stale-age check |

## Error handling

- **localStorage unavailable** (private browsing on some browsers): treat as "consent absent" forever. Dialog re-shows every load. Acceptable degradation.
- **JSON parse failure on the pending flag**: treat as if absent. Clear it.
- **Engine fails to init even after consent**: `useEdgeLLM` already surfaces `error`. The crash flag remains set; on next load, banner appears. User clicks "Switch to Cloud AI" or retries.
- **Multiple tabs** running edge mode concurrently: the first to clear the pending flag on success wins. Other tabs may briefly think they crashed; banner appears, user dismisses. False positive but recoverable.
- **`runEdgeProcessing` throws mid-stream**: `onProgress` and `onChunkResult` simply stop firing. `NoteEditor` sets status to `failed`, leaves the partial `liveConcepts` visible until next edit.

## Testing

### Unit tests

Co-located with the new components, following the existing pattern (`web/src/components/llm/__tests__/`).

- `EdgeConsentDialog.test.tsx` — renders both buttons, fires the right callbacks, dismiss leaves consent absent.
- `EdgeCrashBanner.test.tsx` — renders all three actions, fires the right callbacks.
- `LiveConceptsPreview.test.tsx` — count is correct, popover toggles on click, dedup works on prop changes, hides when empty.
- `useEdgeLLM` integration test — extends the existing tests to cover: consent absent → status `awaiting-consent`; consent declined → status `idle`; recent pending flag → status `awaiting-recovery`; stale pending flag → cleared and normal init.

### Live verification

- Open a fresh browser profile (no localStorage) → expect consent dialog before any download.
- Click Decline → settings flip to cloud mode, no download starts. Reload → no dialog (because `llm_mode === "cloud"` now, and the dialog only triggers when edge mode is selected).
- Manually flip back to edge mode in settings → dialog re-appears (consent flag still says `"declined"`, but the user explicitly chose edge again, so we re-prompt).
- Click Accept → engine starts downloading. Console shows `edge-init-pending` written.
- Edit a note successfully → console shows `markStableInference` called, flag cleared.
- Manually set `localStorage.setItem("neuronote:edge-init-pending", JSON.stringify({startedAt: Date.now()}))` → reload → expect crash banner.
- Edit a long note → expect badge to read `Processing 1/6`, `Processing 2/6`, ..., and the live preview pill to appear after the first chunk and grow.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| User accidentally declines consent and can't get back to edge | They can always re-enable from `LLMSettings`, which re-triggers the dialog because their pref is now cloud (we only check consent when edge is selected). Add a future "Reset consent" button in settings if friction reports come in. |
| Crash banner false-positives on clean tab close mid-load | Acceptable — user clicks "Try Edge AI again", no harm done. Worth telemetry once we have any. |
| `liveConcepts` grows unboundedly on a giant note | Cap to 50 entries with `.slice(-50)` in the dedup logic. Beyond 50, the popover becomes unhelpful anyway. |
| Streaming concepts confuses users when they later see fewer "final" concepts (because dedup ran) | Tooltip on the pill: "Some duplicates will be merged when processing finishes." Defer until a user complains. |
| The crash flag persists across cold-boot reboots and floods banners | The 1-hour stale rule clears it. If a user opens after a reboot more than an hour later, no banner. |

## Out of scope

- Reset-consent UI in settings.
- Showing rule-based candidates as a preview before the LLM filters them (the "C" option from brainstorming we deferred).
- Showing relations as they're discovered (relations need both endpoints; less useful in real time).
- Heartbeat-based crash detection (start without it; add if 1-hour rule misses real crashes).
- Telemetry on crash banner accuracy.
- Memory-pressure detection via the experimental Compute Pressure API (not stable enough yet).
