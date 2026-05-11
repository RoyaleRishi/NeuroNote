import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import {
  CONSENT_KEY,
  PENDING_KEY,
  STALE_PENDING_MS,
} from "../../edge-llm/persistence";

// Mock the model-manager so tests don't touch real WebGPU / workers. The
// initializeEngine stub returns a never-resolving promise so we can read
// intermediate states deterministically; the WebGPU probe defaults to
// supported and is overridden per-test where needed.
vi.mock("../../edge-llm/model-manager", () => ({
  initializeEngine: vi.fn(() => new Promise(() => {})),
  isWebGPUSupported: vi.fn(() => true),
}));

import {
  initializeEngine,
  isWebGPUSupported,
} from "../../edge-llm/model-manager";
import { useEdgeLLM } from "../useEdgeLLM";

describe("useEdgeLLM", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    // Restore default mock return values after clearAllMocks.
    (isWebGPUSupported as ReturnType<typeof vi.fn>).mockReturnValue(true);
    (initializeEngine as ReturnType<typeof vi.fn>).mockImplementation(
      () => new Promise(() => {}),
    );
  });

  it("status is 'idle' when enabled=false", () => {
    const { result } = renderHook(() => useEdgeLLM(false));
    expect(result.current.status).toBe("idle");
    // initializeEngine must not have been called.
    expect(initializeEngine).not.toHaveBeenCalled();
  });

  it("status is 'awaiting-consent' when enabled=true and consent is absent", () => {
    const { result } = renderHook(() => useEdgeLLM(true));
    expect(result.current.status).toBe("awaiting-consent");
    expect(initializeEngine).not.toHaveBeenCalled();
  });

  it("status is 'awaiting-consent' when consent='declined'", () => {
    window.localStorage.setItem(CONSENT_KEY, "declined");
    const { result } = renderHook(() => useEdgeLLM(true));
    expect(result.current.status).toBe("awaiting-consent");
    expect(initializeEngine).not.toHaveBeenCalled();
  });

  it("transitions out of awaiting-consent when consent='accepted' and no pending flag", () => {
    window.localStorage.setItem(CONSENT_KEY, "accepted");
    const { result } = renderHook(() => useEdgeLLM(true));
    expect(result.current.status).not.toBe("awaiting-consent");
    expect(result.current.status).not.toBe("awaiting-recovery");
    expect(initializeEngine).toHaveBeenCalledTimes(1);
  });

  it("status is 'awaiting-recovery' when a fresh pending flag exists", () => {
    window.localStorage.setItem(CONSENT_KEY, "accepted");
    window.localStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ startedAt: Date.now() }),
    );
    const { result } = renderHook(() => useEdgeLLM(true));
    expect(result.current.status).toBe("awaiting-recovery");
    expect(initializeEngine).not.toHaveBeenCalled();
  });

  it("clears stale pending flag and proceeds past recovery gate", () => {
    window.localStorage.setItem(CONSENT_KEY, "accepted");
    // startedAt = 0 is well beyond STALE_PENDING_MS old.
    window.localStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ startedAt: 0 }),
    );
    // Sanity guard: the test relies on Date.now() being far past 0.
    expect(Date.now() - 0).toBeGreaterThan(STALE_PENDING_MS);

    const { result } = renderHook(() => useEdgeLLM(true));
    expect(result.current.status).not.toBe("awaiting-recovery");
    // Stale flag was silently cleared; startInit re-arms a fresh one
    // (with the current timestamp), so the key is present but freshly set.
    const stored = window.localStorage.getItem(PENDING_KEY);
    expect(stored).not.toBeNull();
    const parsed = JSON.parse(stored as string) as { startedAt: number };
    expect(parsed.startedAt).toBeGreaterThan(STALE_PENDING_MS);
    expect(initializeEngine).toHaveBeenCalledTimes(1);
  });

  it("acceptConsent() writes 'accepted' and bumps the token to re-run the effect", () => {
    const { result } = renderHook(() => useEdgeLLM(true));
    expect(result.current.status).toBe("awaiting-consent");
    expect(initializeEngine).not.toHaveBeenCalled();

    act(() => {
      result.current.acceptConsent();
    });

    expect(window.localStorage.getItem(CONSENT_KEY)).toBe("accepted");
    // Effect re-ran and passed the consent gate: initializeEngine was
    // invoked. (Our mock never resolves, so the visible status stays as
    // whatever was last set by the engine — here, no engine callback has
    // fired, so status is unchanged. Asserting on the gate-pass via the
    // initializeEngine call is the deterministic signal.)
    expect(initializeEngine).toHaveBeenCalledTimes(1);
  });

  it("declineConsent() writes 'declined' and sets status to 'idle'", () => {
    const { result } = renderHook(() => useEdgeLLM(true));
    expect(result.current.status).toBe("awaiting-consent");

    act(() => {
      result.current.declineConsent();
    });

    expect(window.localStorage.getItem(CONSENT_KEY)).toBe("declined");
    expect(result.current.status).toBe("idle");
    expect(initializeEngine).not.toHaveBeenCalled();
  });

  it("acknowledgeRecovery('switchToCloud') clears the pending flag and sets status to 'idle'", () => {
    window.localStorage.setItem(CONSENT_KEY, "accepted");
    window.localStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ startedAt: Date.now() }),
    );

    const { result, rerender } = renderHook(
      ({ enabled, retryToken }: { enabled: boolean; retryToken: number }) =>
        useEdgeLLM(enabled, retryToken),
      { initialProps: { enabled: true, retryToken: 0 } },
    );
    expect(result.current.status).toBe("awaiting-recovery");

    act(() => {
      result.current.acknowledgeRecovery("switchToCloud");
    });

    expect(window.localStorage.getItem(PENDING_KEY)).toBeNull();
    expect(result.current.status).toBe("idle");

    // Re-trigger the effect (via retryToken bump, NOT by toggling enabled —
    // toggling enabled would reset recoveryHandledRef) with a fresh pending
    // flag in localStorage: the ref should suppress awaiting-recovery.
    window.localStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ startedAt: Date.now() }),
    );
    rerender({ enabled: true, retryToken: 1 });
    expect(result.current.status).not.toBe("awaiting-recovery");
  });

  it("acknowledgeRecovery('retry') clears the pending flag, sets recovery handled, and re-runs the effect without returning to awaiting-recovery", () => {
    window.localStorage.setItem(CONSENT_KEY, "accepted");
    window.localStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ startedAt: Date.now() }),
    );

    const { result } = renderHook(() => useEdgeLLM(true));
    expect(result.current.status).toBe("awaiting-recovery");
    expect(initializeEngine).not.toHaveBeenCalled();

    act(() => {
      result.current.acknowledgeRecovery("retry");
    });

    // Effect re-ran and skipped the recovery gate (recoveryHandledRef is
    // now true). The deterministic signal is that initializeEngine was
    // invoked. The mock never resolves, so the visible status is whatever
    // the engine last reported (none yet) — the gate-pass is the contract
    // under test, not a status transition.
    expect(initializeEngine).toHaveBeenCalledTimes(1);
    // And startInit re-armed a fresh pending flag.
    expect(window.localStorage.getItem(PENDING_KEY)).not.toBeNull();
  });

  it("markStableInference() clears the pending flag and does not change status", () => {
    window.localStorage.setItem(CONSENT_KEY, "accepted");
    const { result } = renderHook(() => useEdgeLLM(true));
    const statusBefore = result.current.status;

    // Set a pending flag *after* the effect has run, then clear it.
    window.localStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ startedAt: Date.now() }),
    );
    act(() => {
      result.current.markStableInference();
    });

    expect(window.localStorage.getItem(PENDING_KEY)).toBeNull();
    expect(result.current.status).toBe(statusBefore);
  });

  it("crash gate is bypassed on first render when no pending flag exists (e.g., after a previous markStableInference)", () => {
    // Simulate previous-session: consent accepted, flag already cleared.
    window.localStorage.setItem(CONSENT_KEY, "accepted");
    expect(window.localStorage.getItem(PENDING_KEY)).toBeNull();

    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useEdgeLLM(enabled),
      { initialProps: { enabled: false } },
    );
    expect(result.current.status).toBe("idle");

    rerender({ enabled: true });
    expect(result.current.status).not.toBe("awaiting-recovery");
    expect(result.current.status).not.toBe("awaiting-consent");
    expect(initializeEngine).toHaveBeenCalledTimes(1);
  });

  it("WebGPU unsupported: status becomes 'unsupported' and writePendingFlag is NOT called", () => {
    window.localStorage.setItem(CONSENT_KEY, "accepted");
    (isWebGPUSupported as ReturnType<typeof vi.fn>).mockReturnValue(false);

    const { result } = renderHook(() => useEdgeLLM(true));
    expect(result.current.status).toBe("unsupported");
    // The unsupported path returns before writePendingFlag and before
    // initializeEngine. Confirm both: no flag in localStorage, no init call.
    expect(window.localStorage.getItem(PENDING_KEY)).toBeNull();
    expect(initializeEngine).not.toHaveBeenCalled();
  });
});
