import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { ConceptInsightPanel } from "./ConceptInsightPanel";
import type { LocalGraphNode } from "../../../../shared/contracts/ts/v1/graph";

vi.mock("../../lib/api-client", () => ({
  fetchConceptInsight: vi.fn(),
  fetchInsightContext: vi.fn(),
}));
vi.mock("../../lib/hooks/usePreferences", () => ({
  usePreferences: vi.fn(),
}));
vi.mock("../../lib/edge-llm/model-manager", () => ({
  getEngine: vi.fn(),
}));

import { fetchConceptInsight, fetchInsightContext } from "../../lib/api-client";
import { usePreferences } from "../../lib/hooks/usePreferences";
import { getEngine } from "../../lib/edge-llm/model-manager";

const mockFetchConceptInsight = fetchConceptInsight as ReturnType<typeof vi.fn>;
const mockFetchInsightContext = fetchInsightContext as ReturnType<typeof vi.fn>;
const mockUsePreferences = usePreferences as ReturnType<typeof vi.fn>;
const mockGetEngine = getEngine as ReturnType<typeof vi.fn>;

const node: LocalGraphNode = {
  id: "n",
  type: "concept",
  label: "machine learning",
  confidence: null,
  source_note_id: null,
  metadata: {},
};

const cloudPrefs = { llm_mode: "cloud" as const };
const edgePrefs = { llm_mode: "edge" as const };

const cloudInsightResponse = {
  concept_label: "machine learning",
  notes_found: 1,
  note_refs: [{ note_id: "n1", note_title: "Note A", snippet: "...ml..." }],
  insight: "Machine learning is a subset of AI.",
  insight_error: null,
  learning_links: [],
  generated_at: "2026-06-21T00:00:00Z",
};

const contextResponse = {
  concept_label: "machine learning",
  notes: [{ note_id: "n1", title: "Note A", excerpt: "...ml..." }],
  total_notes: 1,
};

function makeEngine(insight = "Edge-generated insight about machine learning.") {
  return {
    chat: {
      completions: {
        create: vi.fn().mockResolvedValue({
          choices: [
            {
              message: {
                content: JSON.stringify({
                  insight,
                  learning_links: [{ title: "ML Intro", url: "https://example.com", description: "Overview" }],
                }),
              },
            },
          ],
        }),
      },
    },
  };
}

describe("ConceptInsightPanel — cloud mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUsePreferences.mockReturnValue({ prefs: cloudPrefs, loading: false, reload: vi.fn(), mutate: vi.fn() });
  });

  it("renders the insight when cloud LLM returns one", async () => {
    mockFetchConceptInsight.mockResolvedValue(cloudInsightResponse);

    render(
      <ConceptInsightPanel node={node} baseUrl="http://localhost:8000" onClose={() => {}} onOpenNote={() => {}} />,
    );

    await waitFor(() =>
      expect(screen.getByText("Machine learning is a subset of AI.")).toBeInTheDocument(),
    );
    expect(mockFetchInsightContext).not.toHaveBeenCalled();
  });

  it("renders the insight_error string when cloud LLM call fails", async () => {
    mockFetchConceptInsight.mockResolvedValue({
      ...cloudInsightResponse,
      insight: null,
      insight_error: "model: claude-3-5-haiku-latest not found",
    });

    render(
      <ConceptInsightPanel node={node} baseUrl="http://localhost:8000" onClose={() => {}} onOpenNote={() => {}} />,
    );

    await waitFor(() =>
      expect(screen.getByText(/claude-3-5-haiku-latest not found/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Set/)).not.toBeInTheDocument();
  });

  it("shows cloud key prompt when no key is configured (insight and insight_error both null)", async () => {
    mockFetchConceptInsight.mockResolvedValue({
      ...cloudInsightResponse,
      insight: null,
      insight_error: null,
    });

    render(
      <ConceptInsightPanel node={node} baseUrl="http://localhost:8000" onClose={() => {}} onOpenNote={() => {}} />,
    );

    await waitFor(() =>
      expect(screen.getByText(/Configure a cloud AI key/i)).toBeInTheDocument(),
    );
  });
});

describe("ConceptInsightPanel — edge mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUsePreferences.mockReturnValue({ prefs: edgePrefs, loading: false, reload: vi.fn(), mutate: vi.fn() });
    mockFetchInsightContext.mockResolvedValue(contextResponse);
  });

  it("uses on-device engine to generate insight and renders it", async () => {
    const engine = makeEngine();
    mockGetEngine.mockReturnValue(engine);

    render(
      <ConceptInsightPanel node={node} baseUrl="http://localhost:8000" onClose={() => {}} onOpenNote={() => {}} />,
    );

    await waitFor(() =>
      expect(screen.getByText("Edge-generated insight about machine learning.")).toBeInTheDocument(),
    );
    expect(mockFetchConceptInsight).not.toHaveBeenCalled();
    expect(mockFetchInsightContext).toHaveBeenCalledWith("http://localhost:8000", "machine learning", 10);
  });

  it("shows loading message when on-device model is not yet ready", async () => {
    mockGetEngine.mockReturnValue(null);

    render(
      <ConceptInsightPanel node={node} baseUrl="http://localhost:8000" onClose={() => {}} onOpenNote={() => {}} />,
    );

    await waitFor(() =>
      expect(screen.getByText(/on-device AI is still loading/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Configure a cloud AI key/i)).not.toBeInTheDocument();
  });

  it("shows error message when on-device inference fails", async () => {
    const engine = {
      chat: { completions: { create: vi.fn().mockRejectedValue(new Error("WebGPU OOM")) } },
    };
    mockGetEngine.mockReturnValue(engine);

    render(
      <ConceptInsightPanel node={node} baseUrl="http://localhost:8000" onClose={() => {}} onOpenNote={() => {}} />,
    );

    await waitFor(() =>
      expect(screen.getByText(/on-device AI insight unavailable/i)).toBeInTheDocument(),
    );
  });

  it("does not show cloud key prompt in edge mode", async () => {
    mockGetEngine.mockReturnValue(null);

    render(
      <ConceptInsightPanel node={node} baseUrl="http://localhost:8000" onClose={() => {}} onOpenNote={() => {}} />,
    );

    await waitFor(() => screen.getByText(/on-device AI is still loading/i));
    expect(screen.queryByText(/Configure a cloud AI key/i)).not.toBeInTheDocument();
  });
});
