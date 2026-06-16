import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("../api-client", () => ({
  fetchPreferences: vi.fn(),
  updatePreferences: vi.fn(),
}));

// Capture showToast calls without needing a real ToastProvider.
const mockShowToast = vi.fn();
vi.mock("../toast", () => ({
  useOptionalToast: () => ({ showToast: mockShowToast, toasts: [], removeToast: vi.fn() }),
}));

import { fetchPreferences, updatePreferences } from "../api-client";
import { PreferencesProvider } from "./PreferencesProvider";
import { usePreferences } from "../hooks/usePreferences";

const edgePrefs = {
  llm_mode: "edge" as const,
  llm_api_key: "",
  llm_base_url: "https://api.openai.com/v1",
  llm_model: "gpt-4o-mini",
  node_salience_threshold: 0.5,
  relationship_confidence_threshold: 0.5,
};

/** Reads `llm_mode` — stands in for any second consumer (e.g. the editor). */
function ModeReadout() {
  const { prefs } = usePreferences();
  return <span data-testid="mode">{prefs?.llm_mode ?? "—"}</span>;
}

/**
 * Writes a new mode via the shared `mutate` — stands in for the UserMenu.
 * Errors are swallowed here so unhandled-rejection noise doesn't leak into
 * tests that assert on toast/prefs rather than on the thrown error.
 */
function ModeWriter() {
  const { mutate } = usePreferences();
  return (
    <button onClick={() => void mutate({ llm_mode: "cloud" }).catch(() => {})}>
      switch
    </button>
  );
}

describe("PreferencesProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockShowToast.mockClear();
    (fetchPreferences as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(edgePrefs);
    (updatePreferences as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...edgePrefs,
      llm_mode: "cloud",
    });
  });

  it("propagates a mutation from one consumer to another without a reload", async () => {
    render(
      <PreferencesProvider>
        <ModeReadout />
        <ModeWriter />
      </PreferencesProvider>,
    );

    // Initial load resolves to edge.
    await waitFor(() => expect(screen.getByTestId("mode")).toHaveTextContent("edge"));

    // A write in the "menu" consumer is reflected in the "editor" consumer.
    fireEvent.click(screen.getByRole("button", { name: "switch" }));
    await waitFor(() => expect(screen.getByTestId("mode")).toHaveTextContent("cloud"));

    // Adopted the PUT response directly — no second GET.
    expect(fetchPreferences).toHaveBeenCalledTimes(1);
  });

  it("shows an error toast and retains previous prefs when mutate() fails", async () => {
    const networkError = new Error("Network error");
    (updatePreferences as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(networkError);

    render(
      <PreferencesProvider>
        <ModeReadout />
        <ModeWriter />
      </PreferencesProvider>,
    );

    // Initial load: edge prefs loaded.
    await waitFor(() => expect(screen.getByTestId("mode")).toHaveTextContent("edge"));

    // Attempt mutation that will fail.
    fireEvent.click(screen.getByRole("button", { name: "switch" }));

    // Error toast must be shown with the error message.
    await waitFor(() =>
      expect(mockShowToast).toHaveBeenCalledWith("Network error", "error"),
    );

    // Prefs must remain at the previous value — no optimistic update.
    expect(screen.getByTestId("mode")).toHaveTextContent("edge");
  });

  it("shows a generic toast message when the error is not an Error instance", async () => {
    (updatePreferences as unknown as ReturnType<typeof vi.fn>).mockRejectedValue("string error");

    render(
      <PreferencesProvider>
        <ModeReadout />
        <ModeWriter />
      </PreferencesProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("mode")).toHaveTextContent("edge"));

    fireEvent.click(screen.getByRole("button", { name: "switch" }));

    await waitFor(() =>
      expect(mockShowToast).toHaveBeenCalledWith("Failed to save preferences", "error"),
    );

    expect(screen.getByTestId("mode")).toHaveTextContent("edge");
  });

  it("re-throws after a failed mutate() so callers can handle the error", async () => {
    const networkError = new Error("timeout");
    (updatePreferences as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(networkError);

    let caughtError: unknown;

    function ErrorCapture() {
      const { mutate } = usePreferences();
      return (
        <button
          onClick={() =>
            void mutate({ llm_mode: "cloud" }).catch((e) => {
              caughtError = e;
            })
          }
        >
          switch
        </button>
      );
    }

    render(
      <PreferencesProvider>
        <ErrorCapture />
      </PreferencesProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "switch" }));

    await waitFor(() => expect(caughtError).toBe(networkError));
  });
});
