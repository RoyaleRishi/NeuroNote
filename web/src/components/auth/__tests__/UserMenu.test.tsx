import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../../../lib/api-client", () => ({
  logoutUser: vi.fn().mockResolvedValue(undefined),
  updatePreferences: vi.fn().mockResolvedValue({
    llm_mode: "edge",
    llm_api_key: "",
    llm_base_url: "https://api.openai.com/v1",
    llm_model: "gpt-4o-mini",
    confidence_threshold: 0.9,
  }),
  fetchPreferences: vi.fn().mockResolvedValue({
    llm_mode: "edge",
    llm_api_key: "",
    llm_base_url: "https://api.openai.com/v1",
    llm_model: "gpt-4o-mini",
    confidence_threshold: 0.9,
  }),
}));

import { UserMenu } from "../UserMenu";
import { updatePreferences, logoutUser } from "../../../lib/api-client";

const mockUser = {
  id: "user-1",
  email: "test@example.com",
  display_name: "Test User",
  avatar_url: null,
  schema_name: "user_abc",
  oauth_provider: "google",
};

describe("UserMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders avatar button with initials when no avatar_url", () => {
    render(<UserMenu user={mockUser} />);
    expect(screen.getByRole("button", { name: "Open settings" })).toBeInTheDocument();
    expect(screen.getByText("TU")).toBeInTheDocument();
  });

  it("renders avatar img when avatar_url is set", () => {
    render(<UserMenu user={{ ...mockUser, avatar_url: "https://example.com/avatar.jpg" }} />);
    const img = screen.getByRole("img", { name: "Test User" });
    expect(img).toBeInTheDocument();
  });

  it("opens dropdown when avatar button is clicked", async () => {
    render(<UserMenu user={mockUser} />);
    expect(screen.queryByText("test@example.com")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() => expect(screen.getByText("test@example.com")).toBeInTheDocument());
  });

  it("closes dropdown when Escape is pressed", async () => {
    render(<UserMenu user={mockUser} />);
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() => expect(screen.getByText("test@example.com")).toBeInTheDocument());
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("test@example.com")).not.toBeInTheDocument());
  });

  it("calls updatePreferences with llm_mode cloud when the Cloud pill clicked", async () => {
    render(<UserMenu user={mockUser} />);
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() => screen.getByRole("button", { name: "Cloud" }));
    fireEvent.click(screen.getByRole("button", { name: "Cloud" }));
    await waitFor(() =>
      expect(updatePreferences).toHaveBeenCalledWith(expect.objectContaining({ llm_mode: "cloud" }))
    );
  });

  it("shows cloud config fields when cloud summaries mode is active", async () => {
    const { fetchPreferences } = await import("../../../lib/api-client");
    vi.mocked(fetchPreferences).mockResolvedValue({
      llm_mode: "cloud",
      llm_api_key: "****abcd",
      llm_base_url: "https://api.openai.com/v1",
      llm_model: "gpt-4o-mini",
      confidence_threshold: 0.9,
    });
    render(<UserMenu user={mockUser} />);
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() => screen.getByPlaceholderText(/API Key/i));
    expect(screen.getByPlaceholderText(/Base URL/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Model/i)).toBeInTheDocument();
  });

  it("calls logoutUser and redirects on sign out", async () => {
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "" },
    });
    render(<UserMenu user={mockUser} />);
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() => screen.getByRole("button", { name: /sign out/i }));
    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));
    await waitFor(() => expect(logoutUser).toHaveBeenCalledTimes(1));
    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });
});
