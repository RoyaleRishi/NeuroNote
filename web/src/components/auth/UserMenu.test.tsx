import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("../../lib/api-client", () => ({
  logoutUser: vi.fn(),
  testLlmConnection: vi.fn(),
}));
vi.mock("../../lib/hooks/usePreferences", () => ({
  usePreferences: vi.fn(),
}));

import { testLlmConnection } from "../../lib/api-client";
import { usePreferences } from "../../lib/hooks/usePreferences";
import { ToastProvider } from "../../lib/toast";
import { ToastContainer } from "../ui/ToastContainer";

import { UserMenu } from "./UserMenu";

const user = {
  user_id: "u1",
  email: "u@example.com",
  display_name: "User",
  avatar_url: null,
  schema_name: "user_test",
};

const cloudPrefs = {
  llm_mode: "cloud" as const,
  llm_api_key: "",
  llm_base_url: "https://api.anthropic.com/v1",
  llm_model: "claude-3-5-haiku-latest",
  node_salience_threshold: 0.5,
  relationship_confidence_threshold: 0.5,
};

let mutate: ReturnType<typeof vi.fn>;

/** Render the menu inside the real toast providers so toasts can be asserted. */
function renderMenu() {
  return render(
    <ToastProvider>
      <UserMenu user={user as unknown as never} />
      <ToastContainer />
    </ToastProvider>,
  );
}

describe("UserMenu — feedback & persistence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mutate = vi.fn().mockResolvedValue(cloudPrefs);
    (usePreferences as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      prefs: cloudPrefs,
      loading: false,
      reload: vi.fn(),
      mutate,
    });
  });

  it("surfaces test-connection failure inline after Save", async () => {
    (testLlmConnection as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      success: false,
      message: "model: claude-3-5-haiku-latest not found",
    });

    renderMenu();
    fireEvent.click(screen.getByLabelText("Open settings"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/claude-3-5-haiku-latest not found/),
      ).toBeInTheDocument(),
    );
    expect(mutate).toHaveBeenCalled();
    expect(testLlmConnection).toHaveBeenCalled();
  });

  it("shows success indicator when test-connection passes", async () => {
    (testLlmConnection as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      success: true,
      message: "Connection successful.",
    });

    renderMenu();
    fireEvent.click(screen.getByLabelText("Open settings"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(screen.getByText(/Connection successful/i)).toBeInTheDocument(),
    );
  });

  it("fires a success toast after saving cloud settings (no reload needed)", async () => {
    (testLlmConnection as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      success: true,
      message: "Connection successful.",
    });

    renderMenu();
    fireEvent.click(screen.getByLabelText("Open settings"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(screen.getByText("Cloud summary settings saved")).toBeInTheDocument(),
    );
  });

  it("toasts and persists when the summaries engine is toggled", async () => {
    renderMenu();
    fireEvent.click(screen.getByLabelText("Open settings"));
    fireEvent.click(screen.getByRole("button", { name: "On-device" }));

    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith(expect.objectContaining({ llm_mode: "edge" })),
    );
    await waitFor(() =>
      expect(screen.getByText("Summaries: on-device")).toBeInTheDocument(),
    );
  });

  it("drives two decoupled sliders, holding each optimistically and persisting its own key", () => {
    vi.useFakeTimers();
    try {
      renderMenu();
      fireEvent.click(screen.getByLabelText("Open settings"));

      const nodeSlider = screen.getByLabelText(
        "Concept relevance threshold",
      ) as HTMLInputElement;
      const relSlider = screen.getByLabelText(
        "Relationship strength threshold",
      ) as HTMLInputElement;
      // Both start at the persisted 50%.
      expect(nodeSlider.value).toBe("0.5");
      expect(relSlider.value).toBe("0.5");

      // Drag concept-relevance: the value holds immediately (no snap-back) and
      // persists under node_salience_threshold after the debounce.
      fireEvent.change(nodeSlider, { target: { value: "0.7" } });
      expect(nodeSlider.value).toBe("0.7");
      expect(screen.getByText("70%")).toBeInTheDocument();
      act(() => vi.advanceTimersByTime(600));
      expect(mutate).toHaveBeenCalledWith({ node_salience_threshold: 0.7 });

      // Drag relationship-strength: persists independently under its own key.
      fireEvent.change(relSlider, { target: { value: "0.9" } });
      expect(relSlider.value).toBe("0.9");
      act(() => vi.advanceTimersByTime(600));
      expect(mutate).toHaveBeenCalledWith({ relationship_confidence_threshold: 0.9 });
    } finally {
      vi.useRealTimers();
    }
  });
});
