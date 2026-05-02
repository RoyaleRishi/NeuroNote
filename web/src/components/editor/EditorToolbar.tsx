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
