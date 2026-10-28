"""Matched peers for event companies (early-warning control group).

For each event company (first event date D):
  - SIC code from the submissions API.
  - Total assets from the XBRL frames API (us-gaap:Assets, USD, instant frame of
    the last calendar quarter ending before D); companyfacts as fallback.
  - Candidates: companies with the same SIC (EDGAR company browse by SIC) that
    appear in the same assets frame with assets within [0.5x, 2x], closest first.
  - Excluded: any company in events.json, and any company whose 8-Ks within
    +/- 2 years of D match covenant-trouble phrases in EDGAR full-text search
    (a failed search also excludes the candidate: no evidence, no peer).
Up to 3 peers per event company. Output: data/groundtruth/peers.json (list of
UniverseEntry with role="peer", peer_of=event CIK).

Run:  uv run python -m validation.peers
"""

from __future__ import annotations

import json
import math
import re
import sys
from datetime import date, timedelta

import httpx

from shared import edgar
from shared.paths import GROUNDTRUTH
from shared.schema import UniverseEntry

from validation import events

OUT = GROUNDTRUTH / "peers.json"
EFTS = "https://efts.sec.gov/LATEST/search-index"
TROUBLE_Q = " OR ".join(f'"{p}"' for p in [
    "agreed to waive", "Waiver and Amendment", "Amendment and Waiver", "Limited Waiver", "forbearance agreement",
    "covenant relief", "not in compliance with the financial covenant", "notice of default",
    "Event of Default has occurred", "notice of acceleration", "covenant waiver",
])


def frame_for(d: date) -> str:
    """Instant frame of the last calendar quarter ending strictly before d, e.g. CY2022Q4I."""
    q = (d.month - 1) // 3  # quarters fully completed this year
    y = d.year
    if q == 0:
        y, q = y - 1, 4
    return f"CY{y}Q{q}I"


_frames: dict[str, dict[str, float]] = {}


def assets_frame(frame: str) -> dict[str, float]:
    if frame not in _frames:
        try:
            data = edgar.get_json(f"https://data.sec.gov/api/xbrl/frames/us-gaap/Assets/USD/{frame}.json")
            _frames[frame] = {str(r["cik"]).zfill(10): float(r["val"]) for r in data.get("data", [])}
        except Exception:
            _frames[frame] = {}
    return _frames[frame]


def assets_from_facts(cik: str, d: date) -> float | None:
    try:
        facts = edgar.company_facts(cik)
    except Exception:
        return None
    rows = facts.get("facts", {}).get("us-gaap", {}).get("Assets", {}).get("units", {}).get("USD", [])
    best = None
    for r in rows:
        try:
            end = date.fromisoformat(r["end"])
        except (KeyError, ValueError):
            continue
        if end <= d and (d - end).days <= 400 and (best is None or end > best[0]):
            best = (end, float(r["val"]))
    return best[1] if best else None


def sic_of(cik: str) -> str | None:
    try:
        return edgar.submissions(cik).get("sic") or None
    except Exception:
        return None


_sic_members: dict[str, list[str]] = {}


def companies_in_sic(sic: str, max_pages: int = 15) -> list[str]:
    if sic in _sic_members:
        return _sic_members[sic]
    out: list[str] = []
    for p in range(max_pages):
        url = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}&owner=include"
               f"&count=100&start={p * 100}&output=atom")
        try:
            body = edgar.get(url).decode("latin-1")
        except Exception:
            break
        ciks = re.findall(r"<cik>(\d+)</cik>", body)
        new = [c.zfill(10) for c in ciks if c.zfill(10) not in out]
        if not new:
            break
        out.extend(new)
    _sic_members[sic] = out
    return out


def has_trouble(cik: str, d: date) -> bool:
    """True if the company's 8-Ks within +/- 2y of d match covenant-trouble phrases, or the search fails."""
    start = (d - timedelta(days=730)).isoformat()
    end = (d + timedelta(days=730)).isoformat()
    params = {"q": TROUBLE_Q, "forms": "8-K", "dateRange": "custom", "startdt": start, "enddt": end, "ciks": cik}
    try:
        data = edgar.get_json(str(httpx.URL(EFTS, params=params)), use_cache=False)
        return data["hits"]["total"]["value"] > 0
    except Exception:
        return True


def peers_for(cik: str, d: date, event_ciks: set[str], k: int = 3, max_checks: int = 8) -> list[str]:
    sic = sic_of(cik)
    if not sic:
        return []
    frame = assets_frame(frame_for(d))
    a0 = frame.get(cik) or assets_from_facts(cik, d)
    if not a0 or a0 <= 0:
        return []
    cands = []
    for c in companies_in_sic(sic):
        if c == cik or c in event_ciks:
            continue
        a = frame.get(c)
        if a and 0.5 * a0 <= a <= 2 * a0:
            cands.append((abs(math.log(a / a0)), c))
    cands.sort()
    chosen: list[str] = []
    for _, c in cands[:max_checks]:
        if has_trouble(c, d):
            continue
        chosen.append(c)
        if len(chosen) >= k:
            break
    return chosen


def run(k: int = 3) -> list[UniverseEntry]:
    evs = events.load()
    event_ciks = {e.cik for e in evs}
    first: dict[str, date] = {}
    for e in evs:
        first[e.cik] = min(first.get(e.cik, e.date), e.date)
    out: list[UniverseEntry] = []
    used: set[str] = set()
    for i, (cik, d) in enumerate(sorted(first.items())):
        ps = [p for p in peers_for(cik, d, event_ciks | used, k) if p not in used]
        used.update(ps)
        out.extend(UniverseEntry(cik=p, role="peer", peer_of=cik) for p in ps)
        print(f"  [{i + 1}/{len(first)}] {cik} {d}: {len(ps)} peers", file=sys.stderr)
        save(out)
    save(out)
    return out


def save(entries: list[UniverseEntry]) -> None:
    GROUNDTRUTH.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps([e.model_dump(mode="json") for e in entries], indent=1))
    tmp.replace(OUT)


def load() -> list[UniverseEntry]:
    if not OUT.exists():
        return []
    return [UniverseEntry.model_validate(x) for x in json.loads(OUT.read_text())]


if __name__ == "__main__":
    ps = run()
    print(f"{len(ps)} peers for {len({p.peer_of for p in ps})} event companies")
