import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("../../lib/api-client", () => ({
  logoutUser: vi.fn(),
  updatePreferences: vi.fn(),
  testLlmConnection: vi.fn(),
}));
vi.mock("../../lib/hooks/usePreferences", () => ({
  usePreferences: vi.fn(),
}));

import { updatePreferences, testLlmConnection } from "../../lib/api-client";
import { usePreferences } from "../../lib/hooks/usePreferences";

import { UserMenu } from "./UserMenu";

const user = {
  user_id: "u1",
  email: "u@example.com",
  display_name: "User",
  avatar_url: null,
  schema_name: "user_test",
};

describe("UserMenu — cloud save validation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (usePreferences as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      prefs: {
        llm_mode: "cloud",
        llm_api_key: "",
        llm_base_url: "https://api.anthropic.com/v1",
        llm_model: "claude-3-5-haiku-latest",
        confidence_threshold: 0.9,
      },
      reload: vi.fn(),
    });
    (updatePreferences as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      llm_mode: "cloud",
      llm_api_key: "****abcd",
      llm_base_url: "https://api.anthropic.com/v1",
      llm_model: "claude-3-5-haiku-latest",
      confidence_threshold: 0.9,
    });
  });

  it("surfaces test-connection failure inline after Save", async () => {
    (testLlmConnection as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      success: false,
      message: "model: claude-3-5-haiku-latest not found",
    });

    render(<UserMenu user={user as unknown as never} />);
    fireEvent.click(screen.getByLabelText("Open settings"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/claude-3-5-haiku-latest not found/),
      ).toBeInTheDocument(),
    );
    expect(updatePreferences).toHaveBeenCalled();
    expect(testLlmConnection).toHaveBeenCalled();
  });

  it("shows success indicator when test-connection passes", async () => {
    (testLlmConnection as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      success: true,
      message: "Connection successful.",
    });

    render(<UserMenu user={user as unknown as never} />);
    fireEvent.click(screen.getByLabelText("Open settings"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(screen.getByText(/Connection successful/i)).toBeInTheDocument(),
    );
  });
});
