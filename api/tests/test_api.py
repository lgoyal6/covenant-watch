from fastapi.testclient import TestClient

import api.main as m
from shared.paths import FIXTURES


def client(tmp_path, monkeypatch):
    # point data paths at an empty dir so the fixture fallback is exercised
    monkeypatch.setattr(m, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(m, "EVAL", tmp_path / "eval")
    monkeypatch.setattr(m, "GROUNDTRUTH", tmp_path / "groundtruth")
    return TestClient(m.app)


def test_fixture_fallback(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.get("/companies").json()
    assert r["source"] == "fixture"
    co = r["companies"][0]
    assert co["name"].endswith("(FIXTURE)")
    lev = next(cv for cv in co["covenants"] if cv["id"] == "lev")
    assert lev["status"] == "indeterminate" and lev["latest_period_end"] == "2024-09-30"
    assert c.get("/companies", params={"q": "nomatch"}).json()["companies"] == []


def test_timeline_and_provenance(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    t = c.get("/companies/0000000001/covenants/lev/timeline").json()
    assert len(t["quarters"]) == 8 and len(t["thresholds"]) == 3
    assert t["events"][0]["kind"] == "waiver"
    assert t["disclosed"][0]["reported_value"] == 4.87
    p = c.get("/provenance/1/lev/2024-09-30").json()
    assert {i["term_node"] for i in p["inputs"]} >= {"total_debt", "restructuring"}
    assert p["threshold_clause"]["text"].startswith("and 4.75")
    assert "restructuring" in p["quarter"]["missing"]
    assert c.get("/provenance/1/lev/2020-01-01").status_code == 404


def test_eval_fallback(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.get("/eval").json()
    assert r["source"] == "fixture" and "ratio_accuracy" in r["report"]
