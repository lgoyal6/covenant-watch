"""Re-verify every evidence quote in validation/labels/*.json and print a review sheet.

  uv run python -m validation.labels.check            # all files
  uv run python -m validation.labels.check 0000051253 # files for one CIK
"""

import json
import sys
from pathlib import Path

from validation.text import doc_text

DIR = Path(__file__).resolve().parent
KINDS = {"max_leverage", "max_senior_leverage", "min_interest_coverage", "min_fixed_charge_coverage", "min_liquidity", "other"}
OPS = {"sum", "subtract", "ratio", "leaf", "cap", "floor"}


def quotes(label: dict):
    for c in label.get("covenants", []):
        ev = c.get("evidence") or {}
        if ev.get("covenant"):
            yield f"covenant {c['kind']}", ev["covenant"]
        for i, t in enumerate(ev.get("thresholds") or []):
            yield f"  threshold {i}", t
    for t in label.get("terms", []):
        if t.get("evidence"):
            yield f"term {t['label']}", t["evidence"]


def check(path: Path) -> int:
    label = json.loads(path.read_text())
    problems = 0
    print(f"\n== {path.name}  status={label.get('status')}  {label.get('agreement_url', '')}")
    for c in label.get("covenants", []):
        if c.get("kind") not in KINDS or c.get("direction") not in ("max", "min") or c.get("test_period") not in ("ttm", "quarter", "point_in_time"):
            print(f"  BAD ENUM in covenant {c.get('kind')}")
            problems += 1
        sched = ", ".join(f"{t['value']} [{t['effective_from']}..{t.get('effective_to') or ''}]" for t in c.get("thresholds", []))
        print(f"  {c['kind']:26} {c.get('numerator_label')} / {c.get('denominator_label')}: {sched}")
    for t in label.get("terms", []):
        if t.get("op") not in OPS:
            print(f"  BAD OP {t.get('op')} in term {t.get('label')}")
            problems += 1
    for name, ev in quotes(label):
        try:
            ok = ev["quote"] in doc_text(ev["url"])
        except Exception as e:  # network or bad URL
            ok = False
            print(f"  could not load {ev.get('url')}: {e}")
        if not ok:
            problems += 1
            print(f"  QUOTE NOT FOUND for {name}: {ev.get('quote', '')[:120]!r}")
    for n in label.get("draft_notes", []):
        print(f"  note: {n}")
    print(f"  {'OK' if not problems else f'{problems} PROBLEM(S)'}")
    return problems


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else ""
    files = sorted(p for p in DIR.glob("*.json") if not p.name.startswith("_") and p.name.startswith(want))
    total = sum(check(p) for p in files)
    print(f"\n{len(files)} files, {total} problems")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
