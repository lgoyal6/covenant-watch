import json

from shared.paths import FIXTURES
from shared.schema import CovenantArtifact, GroundTruth
from validation.score import build_report


def fixture_inputs():
    art = CovenantArtifact.model_validate_json((FIXTURES / "artifact_example.json").read_text())
    gt = GroundTruth.model_validate_json((FIXTURES / "groundtruth_example.json").read_text())
    return {"0000000001": art}, gt


def test_ratio_accuracy_on_fixture(tmp_path):
    arts, gt = fixture_inputs()
    report, detail = build_report(arts, gt.disclosed, gt.events, gt.universe, labels_dir=tmp_path, contracts_dir=tmp_path)
    ra = report.ratio_accuracy
    # reported 4.87 vs computed 4.868 for 2024-06-30 (a point: low == high)
    assert ra["n"] == 1 and ra["pct_inside_range"] == 0.0
    assert abs(ra["median_abs_error"] - 0.002) < 1e-9
    assert ra["pct_within_0_05"] == 1.0
    assert ra["threshold_agreement"] == 1.0  # reported max 5.25 == extracted threshold in force


def test_early_warning_on_fixture(tmp_path):
    arts, gt = fixture_inputs()
    report, detail = build_report(arts, gt.disclosed, gt.events, gt.universe, labels_dir=tmp_path, contracts_dir=tmp_path)
    ew = report.early_warning
    # waiver 2024-11-12; the 2024-06-30 leverage quarter is a warning, ~2 quarters earlier
    assert ew["events_scored"] == 1 and ew["hit_rate"] == 1.0
    assert ew["median_lead_quarters"] == 2
    assert ew["peers_scored"] == 0  # the fixture peer has no artifact
    assert report.refusals["missing_filing"] == 1


def test_extraction_scoring(tmp_path):
    contracts = tmp_path / "contracts"
    labels = tmp_path / "labels"
    contracts.mkdir()
    labels.mkdir()
    (contracts / "0000000001.json").write_text((FIXTURES / "contract_example.json").read_text())
    gold = {"cik": "1", "agreement_accession": "0000000001-22-000010", "status": "labeled",
            "covenants": [{"kind": "max_leverage", "direction": "max", "test_period": "ttm",
                           "thresholds": [{"value": 4.5, "effective_from": "2022-03-15", "effective_to": None}, {"value": 6.0, "effective_from": "2023-01-01"}]},
                          {"kind": "min_fixed_charge_coverage", "direction": "min", "test_period": "ttm", "thresholds": []}],
            "terms": [{"label": "Consolidated EBITDA", "children_labels": ["EBITDA before addbacks", "non-cash charges", "something else"]}]}
    (labels / "a.json").write_text(json.dumps(gold))
    (labels / "b.json").write_text(json.dumps({**gold, "status": "template"}))
    (labels / "c.json").write_text(json.dumps({**gold, "agreement_accession": "other-agreement"}))
    arts, gt = fixture_inputs()
    report, _ = build_report(arts, gt.disclosed, gt.events, gt.universe, labels_dir=labels, contracts_dir=contracts)
    ex = report.extraction
    assert ex["agreements_labeled"] == 1 and ex["agreement_mismatch"] == 1
    assert ex["covenant_kind"] == {"precision": 0.5, "recall": 0.5, "tp": 1, "fp": 1, "fn": 1}
    assert ex["threshold_value"]["tp"] == 1 and ex["threshold_value"]["fn"] == 1
    assert ex["term_structure"]["tp"] == 2 and ex["term_structure"]["fn"] == 1
