from shared.contracts.python.v1.parity import GraphParityReport


def test_parity_report_defaults_to_zero_counts():
    report = GraphParityReport()
    assert report.pruned_note_artifacts == 0
    assert report.pruned_concept_nodes == 0
    assert report.pruned_subject_nodes == 0
    assert report.pruned_registry_rows == 0
    assert report.reprocessed_notes == 0


def test_parity_report_roundtrips_counts():
    report = GraphParityReport(
        pruned_note_artifacts=3,
        pruned_concept_nodes=12,
        pruned_subject_nodes=1,
        pruned_registry_rows=12,
        reprocessed_notes=0,
    )
    assert report.model_dump()["pruned_concept_nodes"] == 12
