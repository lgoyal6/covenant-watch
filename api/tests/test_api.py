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


def test_overview_fixture(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    o = c.get("/overview").json()
    assert o["source"] == "fixture" and o["companies"] == 1 and o["covenants"] == 2
    assert o["status_latest"] == {"ok": 0, "warning": 1, "breach": 0, "indeterminate": 1, "refused": 0}
    assert [q["quarter"] for q in o["status_by_quarter"]][:2] == ["2023-Q1", "2023-Q2"]
    assert sum(q["refused"] for q in o["status_by_quarter"]) == 2
    # leverage worst case is -0.31x against 4.75x: closest to breach first
    assert o["closest"][0]["covenant_id"] == "lev" and o["closest"][0]["headroom_pct"] < 0
    assert o["events"][0]["kind"] == "waiver" and o["events"][0]["name"].endswith("(FIXTURE)")
    assert o["refusals"] == {"missing_filing": 1}
    assert o["ratio_accuracy"]["n"] == 1


def test_cal_quarter():
    from datetime import date

    from api.main import _cal_quarter

    assert _cal_quarter(date(2024, 9, 28)) == "2024-Q3"
    assert _cal_quarter(date(2024, 9, 30)) == "2024-Q3"
    assert _cal_quarter(date(2024, 12, 28)) == "2024-Q4"
    assert _cal_quarter(date(2024, 12, 31)) == "2024-Q4"
    assert _cal_quarter(date(2025, 3, 29)) == "2025-Q1"
    assert _cal_quarter(date(2024, 7, 1)) == "2024-Q2"
