"""Build data/universe.json from ground truth: event companies, their peers, disclosed-ratio companies.

Event companies: the subset chosen by peers.select_event_companies (XBRL assets
before the event, >= $250M, largest first, default 40); events.json keeps all.

One entry per CIK (10-digit, zero-padded). Role priority: event > peer > disclosed
(the scorer reads disclosed.json / events.json directly, so the role here only
says why a company is in the run set). Order in the file is the suggested
processing order: events, then their peers, then disclosed companies.

Only XBRL filers are kept (submissions API shows at least one isXBRL filing),
since the engine needs companyfacts.

Run:  uv run python -m validation.universe [--no-xbrl-check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shared import edgar
from shared.paths import GROUNDTRUTH, UNIVERSE
from shared.schema import UniverseEntry

from validation import disclosed, events, peers

PEERS = GROUNDTRUTH / "peers.json"
# committed copy of data/universe.json (data/ is gitignored; Laksh works on another machine)
SNAPSHOT = Path(__file__).resolve().parent / "universe_snapshot.json"


def is_xbrl_filer(cik: str) -> bool:
    try:
        sub = edgar.submissions(cik)
    except Exception:
        return False
    recent = sub.get("filings", {}).get("recent", {})
    return any(recent.get("isXBRL", [])) or any(recent.get("isInlineXBRL", []))


def load_peers() -> list[UniverseEntry]:
    if not PEERS.exists():
        return []
    return [UniverseEntry.model_validate(x) for x in json.loads(PEERS.read_text())]


def build(check_xbrl: bool = True, max_events: int = 40) -> list[UniverseEntry]:
    entries: list[UniverseEntry] = []
    seen: set[str] = set()

    def add(cik: str, role: str, peer_of: str | None = None) -> None:
        cik = cik.zfill(10)
        if cik in seen:
            return
        if check_xbrl and not is_xbrl_filer(cik):
            print(f"  skip {cik}: no XBRL filings", file=sys.stderr)
            return
        seen.add(cik)
        entries.append(UniverseEntry(cik=cik, role=role, peer_of=peer_of))

    evs = events.load()
    event_ciks = {e.cik for e in evs}
    peer_rows = load_peers()
    # events first (selected subset: see peers.select_event_companies), each followed by its peers
    for cik in peers.select_event_companies(max_events):
        add(cik, "event")
        for p in peer_rows:
            if p.peer_of == cik and p.cik not in event_ciks:
                add(p.cik, "peer", cik)
    for cik in dict.fromkeys(r.cik for r in disclosed.load()):
        add(cik, "disclosed")
    return entries


def save(entries: list[UniverseEntry]) -> None:
    UNIVERSE.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps([e.model_dump(mode="json") for e in entries], indent=1)
    for path in (UNIVERSE, SNAPSHOT):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(body)
        tmp.replace(path)


def load() -> list[UniverseEntry]:
    if not UNIVERSE.exists():
        return []
    return [UniverseEntry.model_validate(x) for x in json.loads(UNIVERSE.read_text())]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-xbrl-check", action="store_true")
    ap.add_argument("--max-events", type=int, default=40)
    a = ap.parse_args()
    es = build(check_xbrl=not a.no_xbrl_check, max_events=a.max_events)
    save(es)
    roles: dict[str, int] = {}
    for e in es:
        roles[e.role] = roles.get(e.role, 0) + 1
    print(f"universe: {len(es)} entries {roles}")
