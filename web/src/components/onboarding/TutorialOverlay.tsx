"use client";

import { useState } from "react";

const STORAGE_KEY = "neuronote.tutorial.v1.done";

const STEPS = [
  {
    title: "Welcome to NeuroNote",
    body: "NeuroNote turns your notes into a living knowledge graph. Concepts extract automatically as you write, and link across everything you've ever noted.",
    hint: null,
  },
  {
    title: "Write your first note",
    body: 'Hit "+ New note" in the sidebar to create a note. Write anything — a thought, a research summary, a meeting recap. The pipeline does the rest.',
    hint: 'Try: "+ New note" in the left panel',
  },
  {
    title: "Concepts surface automatically",
    body: "A few seconds after you finish typing, NeuroNote extracts the key concepts from your note. You'll see a count badge appear in the editor toolbar.",
    hint: "Look for the concept badge in the toolbar after saving",
  },
  {
    title: "Tune the graph with confidence sliders",
    body: "Open your user menu (top right) to find two graph sliders. Concept relevance controls which nodes appear — higher means only the most salient concepts show. Relationship strength filters edges — higher keeps only the most confident connections.",
    hint: "User menu → Graph: Concept relevance / Relationship strength",
  },
  {
    title: "Explore your knowledge graph",
    body: "Switch to the Graph tab in the top nav to see all your concepts mapped. Click any concept node for an AI-grounded insight drawn from your own notes.",
    hint: 'Click "Graph" in the top navigation bar',
  },
];

interface TutorialOverlayProps {
  onDone: () => void;
}

export function TutorialOverlay({ onDone }: TutorialOverlayProps) {
  const [step, setStep] = useState(0);

  function advance() {
    if (step < STEPS.length - 1) {
      setStep(step + 1);
    } else {
      finish();
    }
  }

  function finish() {
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      // ignore storage errors
    }
    onDone();
  }

  const current = STEPS[step]!;
  const isLast = step === STEPS.length - 1;

  return (
    <div className="tutorial-overlay" role="dialog" aria-modal="true" aria-label="Getting started">
      <div className="tutorial-card">
        <div className="tutorial-step-dots" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
          {STEPS.map((_, i) => (
            <span
              key={i}
              className={`tutorial-dot${i === step ? " tutorial-dot--active" : ""}`}
            />
          ))}
        </div>

        <h2 className="tutorial-title">{current.title}</h2>
        <p className="tutorial-body">{current.body}</p>
        {current.hint && (
          <p className="tutorial-hint">{current.hint}</p>
        )}

        <div className="tutorial-actions">
          <button type="button" className="tutorial-btn-skip" onClick={finish}>
            Skip tour
          </button>
          <button type="button" className="tutorial-btn-next" onClick={advance}>
            {isLast ? "Done" : "Next →"}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Returns true if the tutorial should be shown (first visit). */
export function shouldShowTutorial(): boolean {
  try {
    return !localStorage.getItem(STORAGE_KEY);
  } catch {
    return false;
  }
}
