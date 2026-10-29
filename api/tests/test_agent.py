from types import SimpleNamespace

import api.main as m
from api.agent import TOOLS, ask, run_tool


def fixture_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "ARTIFACTS", tmp_path / "a")
    monkeypatch.setattr(m, "EVAL", tmp_path / "e")
    monkeypatch.setattr(m, "GROUNDTRUTH", tmp_path / "g")


def test_tools_read_real_views(tmp_path, monkeypatch):
    fixture_paths(tmp_path, monkeypatch)
    out, err = run_tool("covenant_timeline", {"cik": "1", "covenant_id": "lev"})
    assert not err and len(out["quarters"]) == 8 and out["events"][0]["kind"] == "waiver"
    out, err = run_tool("quarter_provenance", {"cik": "1", "covenant_id": "lev", "period_end": "2024-09-30"})
    assert not err and out["quarter"]["status"] == "indeterminate" and out["threshold_clause"].startswith("and 4.75")
    out, err = run_tool("covenant_timeline", {"cik": "999", "covenant_id": "lev"})
    assert err and "no artifact" in out["error"]
    assert {t["name"] for t in TOOLS} == {"search_companies", "portfolio_overview", "covenant_timeline", "quarter_provenance", "company_refusals"}


class Scripted:
    """Stands in for the Anthropic client: first asks for a timeline, then answers."""

    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            return SimpleNamespace(stop_reason="tool_use", model=kw["model"], content=[
                SimpleNamespace(type="tool_use", id="t1", name="covenant_timeline", input={"cik": "1", "covenant_id": "lev"})])
        tool_result = kw["messages"][-1]["content"][0]
        assert tool_result["tool_use_id"] == "t1" and "4.75" in tool_result["content"]
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"], content=[SimpleNamespace(type="text", text="Leverage is indeterminate in Q3 2024.")])


def test_agent_loop_runs_tools_and_answers(tmp_path, monkeypatch):
    fixture_paths(tmp_path, monkeypatch)
    client = Scripted()
    r = ask("Is Example Holdings close to its leverage limit?", cik="1", client=client)
    assert r["answer"].startswith("Leverage is indeterminate")
    assert r["steps"] == [{"tool": "covenant_timeline", "input": {"cik": "1", "covenant_id": "lev"}, "ok": True}]
    assert client.calls[0]["model"] == "claude-opus-5-5" and "CIK 1" in client.calls[0]["messages"][0]["content"]


def test_agent_endpoint_without_key(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import api.agent

    fixture_paths(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(api.agent, "api_key", lambda: None)
    r = TestClient(m.app).post("/agent/ask", json={"question": "hi"})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


class Briefer(Scripted):
    """Overview first, then a timeline, then the memo."""

    def create(self, **kw):
        self.calls.append(kw)
        n = len(self.calls)
        if n == 1:
            return SimpleNamespace(stop_reason="tool_use", model=kw["model"], content=[SimpleNamespace(type="tool_use", id="a", name="portfolio_overview", input={})])
        if n == 2:
            assert '"closest"' in kw["messages"][-1]["content"][0]["content"]
            return SimpleNamespace(stop_reason="tool_use", model=kw["model"], content=[SimpleNamespace(type="tool_use", id="b", name="covenant_timeline", input={"cik": "1", "covenant_id": "lev"})])
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"], content=[SimpleNamespace(type="text", text="## Risk briefing\n1 covenant needs attention.")])


def test_brief_agent_investigates_then_writes(tmp_path, monkeypatch):
    from api.agent import brief

    fixture_paths(tmp_path, monkeypatch)
    c = Briefer()
    r = brief(top=3, client=c)
    assert r["answer"].startswith("## Risk briefing")
    assert [s["tool"] for s in r["steps"]] == ["portfolio_overview", "covenant_timeline"]
    assert c.calls[0]["output_config"]["effort"] == "high" and "3 most at-risk" in c.calls[0]["messages"][0]["content"]


def test_stress_tools_and_breakeven_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    fixture_paths(tmp_path, monkeypatch)
    out, err = run_tool("covenant_breakeven", {"cik": "1"})
    assert not err and {c["covenant_id"] for c in out["covenants"]} == {"lev", "icr"}
    out, err = run_tool("stress_test", {"cik": "1", "covenant_id": "icr", "earnings_change_pct": -25, "other_change_pct": 0})
    assert not err and out["baseline"]["status"] == "warning" and out["status"] in ("breach", "indeterminate")
    r = TestClient(m.app).get("/companies/1/breakeven").json()
    assert r["covenants"][1]["earnings_change_to_breach_pct"] < 0


class Stresser(Scripted):
    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            assert {t["name"] for t in kw["tools"]} == {"covenant_timeline", "company_refusals", "covenant_breakeven", "stress_test"}
            return SimpleNamespace(stop_reason="tool_use", model=kw["model"], content=[SimpleNamespace(type="tool_use", id="s", name="covenant_breakeven", input={"cik": "1"})])
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"], content=[SimpleNamespace(type="text", text="## Stress test: Example\nCoverage trips first.")])


def test_stress_agent(tmp_path, monkeypatch):
    from api.agent import stress_agent

    fixture_paths(tmp_path, monkeypatch)
    r = stress_agent("1", "earnings -30%", client=Stresser())
    assert r["steps"][0]["tool"] == "covenant_breakeven" and r["answer"].startswith("## Stress test")
