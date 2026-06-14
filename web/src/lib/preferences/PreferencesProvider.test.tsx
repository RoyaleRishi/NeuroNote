import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("../api-client", () => ({
  fetchPreferences: vi.fn(),
  updatePreferences: vi.fn(),
}));

import { fetchPreferences, updatePreferences } from "../api-client";
import { PreferencesProvider } from "./PreferencesProvider";
import { usePreferences } from "../hooks/usePreferences";

const edgePrefs = {
  llm_mode: "edge" as const,
  llm_api_key: "",
  llm_base_url: "https://api.openai.com/v1",
  llm_model: "gpt-4o-mini",
  confidence_threshold: 0.9,
};

/** Reads `llm_mode` — stands in for any second consumer (e.g. the editor). */
function ModeReadout() {
  const { prefs } = usePreferences();
  return <span data-testid="mode">{prefs?.llm_mode ?? "—"}</span>;
}

/** Writes a new mode via the shared `mutate` — stands in for the UserMenu. */
function ModeWriter() {
  const { mutate } = usePreferences();
  return (
    <button onClick={() => void mutate({ llm_mode: "cloud" })}>switch</button>
  );
}

describe("PreferencesProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
});
