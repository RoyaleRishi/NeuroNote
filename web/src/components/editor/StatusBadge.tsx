import type { ProcessStatus, SaveStatus } from "../../lib/state/note-store";

const SAVE_STATUS_CONFIG: Record<
  SaveStatus,
  { label: string; icon: string; className: string }
> = {
  idle: { label: "", icon: "", className: "" },
  saving: { label: "Saving", icon: "⏳", className: "status-saving" },
  saved: { label: "Saved", icon: "✓", className: "status-saved" },
  error: { label: "Save failed", icon: "⚠", className: "status-error" },
};

const PROCESS_STATUS_CONFIG: Record<
  ProcessStatus,
  { label: string; icon: string; className: string }
> = {
  idle: { label: "", icon: "", className: "" },
  queued: { label: "Processing queued", icon: "⏱", className: "status-queued" },
  running: { label: "Processing", icon: "⚙", className: "status-running" },
  completed: { label: "Processing complete", icon: "✓", className: "status-completed" },
  failed: { label: "Processing failed", icon: "⚠", className: "status-error" },
};

export function SaveStatusBadge({ status }: { status: SaveStatus }) {
  const config = SAVE_STATUS_CONFIG[status];
  if (!config.label) return null;

  return (
    <span className={`status-badge ${config.className}`} role="status">
      <span className="status-icon" aria-hidden="true">
        {config.icon}
      </span>
      <span className="status-label">{config.label}</span>
    </span>
  );
}

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
      <span className="status-icon" aria-hidden="true">
        {config.icon}
      </span>
      <span className="status-label">{label}</span>
    </span>
  );
}
