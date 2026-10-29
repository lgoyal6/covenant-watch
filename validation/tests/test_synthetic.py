from validation.synthetic import build


def test_synthetic_is_valid_fictional_and_deterministic():
    arts, disclosed, events, universe = build(n=30, seed=1)
    assert len(arts) == 30
    names = [a.contract.company.name for a in arts.values()]
    assert len(set(names)) == 30 and all(n.endswith("(Synthetic)") for n in names)
    assert all(c.startswith("99") for c in arts)  # unused CIK range
    assert all("example.invalid" in a.contract.agreements[0].url for a in arts.values())
    statuses = {q.status for a in arts.values() for q in a.quarters}
    assert {"ok", "breach"} <= statuses  # exercised through engine.compute
    assert {u.role for u in universe} >= {"event", "peer"}
    again = build(n=30, seed=1)[0]
    assert [a.quarters[0].ratio_low for a in again.values()] == [a.quarters[0].ratio_low for a in arts.values()]
