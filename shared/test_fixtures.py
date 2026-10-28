from shared.paths import FIXTURES
from shared.schema import ContractExtraction, CovenantArtifact, EvalReport, GroundTruth


def load(model, name):
    return model.model_validate_json((FIXTURES / name).read_text())


def test_fixtures_match_contract():
    contract = load(ContractExtraction, "contract_example.json")
    artifact = load(CovenantArtifact, "artifact_example.json")
    load(GroundTruth, "groundtruth_example.json")
    load(EvalReport, "eval_example.json")
    assert artifact.contract == contract


def test_definition_tree_is_closed():
    contract = load(ContractExtraction, "contract_example.json")
    ids = {t.id for t in contract.terms}
    for t in contract.terms:
        assert set(t.children) <= ids
        if t.cap and t.cap.get("kind") == "pct_of":
            assert t.cap["of"] in ids
    for c in contract.covenants:
        assert c.numerator_term in ids
        assert c.denominator_term is None or c.denominator_term in ids
