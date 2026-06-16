// Mirror of shared/contracts/python/v1/parity.py — keep in sync.
export interface GraphParityReport {
  pruned_note_artifacts: number;
  pruned_concept_nodes: number;
  pruned_subject_nodes: number;
  pruned_registry_rows: number;
  reprocessed_notes: number;
}
