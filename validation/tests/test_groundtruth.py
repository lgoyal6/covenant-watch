"""Tests for validation ground truth: parsing, classification, dedupe, and span integrity of saved outputs."""

import json
from datetime import date

import pytest

from shared.paths import GROUNDTRUTH, UNIVERSE
from shared.schema import CovenantEvent, DisclosedRatio, Span, UniverseEntry
from validation.disclosed import kind_of, parse_sentence
from validation.events import classify_sentence, dedupe, is_stale
from validation.text import html_to_text, sentence_bounds

P = date(2024, 6, 30)


# ---------------- text ----------------


def test_html_to_text_is_deterministic_and_normalized():
    html = "<html><head><title>x</title></head><body><p>Our&nbsp;Leverage <b>Ratio</b> was 3.2 to 1.00.</p><div>Next</div><ix:header>hidden</ix:header></body></html>"
    t = html_to_text(html)
    assert t == html_to_text(html)
    assert "Our Leverage Ratio was 3.2 to 1.00." in t
    assert "hidden" not in t and "x" not in t.split("\n")[0]


def test_sentence_bounds_skips_abbreviations():
    t = "Intro sentence here. Acme Inc. reported that its Leverage Ratio was 2.0 to 1.00 as of June 30, 2024. Next one."
    pos = t.index("Leverage")
    s, e = sentence_bounds(t, pos)
    assert t[s:e] == "Acme Inc. reported that its Leverage Ratio was 2.0 to 1.00 as of June 30, 2024."


# ---------------- disclosed ratios ----------------


def one(sentence, period=P):
    r = parse_sentence(sentence, period)
    assert len(r) == 1, r
    return r[0]


def test_actual_with_threshold():
    p = one("As of June 30, 2024, our Consolidated Leverage Ratio was 3.2 to 1.00, compared to a maximum of 4.50 to 1.00.")
    assert (p.kind, p.value, p.threshold, p.period_end) == ("max_leverage", 3.2, 4.5, date(2024, 6, 30))


def test_two_ratios_one_sentence():
    r = parse_sentence("As of September 30, 2025, our leverage ratio was 1.70 to 1.00 and our interest coverage ratio was 9.15 to 1.00.", P)
    assert [(x.kind, x.value) for x in r] == [("max_leverage", 1.7), ("min_interest_coverage", 9.15)]
    assert all(x.period_end == date(2025, 9, 30) for x in r)


def test_x_and_times_formats_and_senior_kind():
    assert one("As of September 24, 2025, our consolidated fixed charge coverage ratio was 2.07 times.").kind == "min_fixed_charge_coverage"
    p = one("At September 30, 2025, the Company's first-priority net senior secured leverage ratio was 1.6x.")
    assert (p.kind, p.value) == ("max_senior_leverage", 1.6)


def test_parenthetical_prior_period_date_ignored():
    r = parse_sentence("At September 30, 2025, our leverage ratio was 0.63:1.00 (December 31, 2024: 0.25:1.00), and our interest coverage ratio was 22.70:1.00 (December 31, 2024: 26.84:1.00).", P)
    assert [(x.value, x.period_end) for x in r] == [(0.63, date(2025, 9, 30)), (22.7, date(2025, 9, 30))]


def test_no_date_falls_back_to_filing_period():
    assert one("Our total leverage ratio was 2.5 to 1.00, in compliance with the credit agreement.").period_end == P


@pytest.mark.parametrize("s", [
    "The Credit Agreement requires a maximum consolidated leverage ratio of 4.50 to 1.00.",
    "The Company must maintain a leverage ratio of not more than 3.50 to 1.00.",
    "If the Net First Lien Leverage Ratio was greater than 1.80 to 1.00, the applicable margin shall equal 1.25%.",
    "As of March 31, 2024, our first lien net leverage ratio was less than 4.25:1.00.",
    "On a pro forma basis, our leverage ratio was 3.0 to 1.00.",
    "The leverage ratio shall not exceed 4.50 to 1.00 as of the last day of any fiscal quarter.",
    "Available Liquidity includes the trigger level that constrains borrowing until a fixed charge coverage ratio of 1.05 to 1.00 is achieved.",
    "Maximum permitted level of the senior secured leverage ratio was 3.75 to 1.0 at March 31, 2021 under Amendment No. 4.",
    "Our leverage ratio was 3.1 to 1.00 and 3.4 to 1.00 as of June 30, 2024 and December 31, 2023, respectively.",
])
def test_rejects_thresholds_conditionals_proforma_ambiguous(s):
    assert parse_sentence(s, P) == []


def test_kind_mapping():
    assert kind_of("Consolidated Total Net Leverage Ratio") == "max_leverage"
    assert kind_of("First Lien Net Leverage Ratio") == "max_senior_leverage"
    assert kind_of("Interest Coverage Ratio") == "min_interest_coverage"
    assert kind_of("Fixed Charge Coverage Ratio") == "min_fixed_charge_coverage"
    assert kind_of("Net Debt to Consolidated Adjusted EBITDA ratio") == "max_leverage"
    assert kind_of("interest and dividend coverage ratio") == "min_interest_coverage"


# ---------------- events ----------------

F = date(2018, 8, 28)


@pytest.mark.parametrize("s,kind", [
    ("Additionally, the lenders agreed to waive the requirements that the Company comply with certain financial covenants until December 31, 2018.", "waiver"),
    ("The Consolidated Net Leverage Ratio financial covenant has been amended to increase the maximum leverage ratio thereunder from 3.75:1.0 to 4.50:1.0.", "amendment_loosening"),
    ("The Amendment provides for a financial covenant relief period through the fiscal quarter ending June 30, 2018 under the credit agreement.", "amendment_loosening"),
    ("On July 9, 2018, the Company received a Notice of Default from the Lender under the Loan Agreement.", "default"),
    ("On August 1, 2018, the Company received from the Agent a written notice of acceleration of the outstanding amounts due under the Credit Agreement.", "acceleration"),
    ("As of June 30, 2018, the Company was not in compliance with the fixed charge coverage ratio covenant under its credit facility.", "default"),
])
def test_event_positive(s, kind):
    assert classify_sentence(s, F) == kind


@pytest.mark.parametrize("s", [
    "If we fail to comply with the financial covenants, the lenders could declare all amounts outstanding immediately due and payable.",
    "Any failure to comply with these covenants may result in an event of default under the credit agreement.",
    "For purposes hereof, the term Pre-Existing Claims means any Event of Default with respect to which the Lender has accelerated the maturity date of the Loan.",
    "The Agent delivered the Notice of Default, without waiving any rights, remedies, powers, privileges and defenses afforded under the Credit Agreement.",
    "For the quarter ended September 30, 2016, the Company was not in compliance with the financial covenant in its credit agreement.",
    "than notice of acceleration.",
])
def test_event_negative(s):
    assert classify_sentence(s, F) is None


def test_is_stale():
    assert is_stale("In February 2016, the facility was amended.", F)
    assert not is_stale("On August 1, 2018, the facility was amended.", F)
    assert not is_stale("No dates here.", F)


def _ev(cik, d, kind, text=None):
    text = text or f"{kind} on {d:%B} {'abcdefghijklmnopqrstuvwxyzab'[d.day]}"
    return CovenantEvent(cik=cik, date=d, kind=kind, span=Span(accession="a", url="u", char_start=0, char_end=len(text), text=text))


def test_dedupe_same_kind_within_60_days_keeps_earliest():
    evs = [
        _ev("1", date(2020, 4, 1), "waiver"),
        _ev("1", date(2020, 5, 15), "waiver"),  # 44 days -> dropped
        _ev("1", date(2020, 8, 1), "waiver"),  # 122 days after kept one -> kept
        _ev("1", date(2020, 4, 10), "default"),  # different kind -> kept
        _ev("2", date(2020, 4, 2), "waiver"),  # different company -> kept
    ]
    out = dedupe(evs)
    assert [(e.cik, e.date, e.kind) for e in out] == [
        ("1", date(2020, 4, 1), "waiver"),
        ("1", date(2020, 4, 10), "default"),
        ("1", date(2020, 8, 1), "waiver"),
        ("2", date(2020, 4, 2), "waiver"),
    ]


def test_dedupe_same_sentence_repeated_in_later_filings():
    t = "We amended our credit facility in the second quarter of 2020 to increase the maximum leverage ratio."
    out = dedupe([_ev("1", date(2020, 7, 22), "amendment_loosening", t), _ev("1", date(2020, 10, 21), "amendment_loosening", t)])
    assert [e.date for e in out] == [date(2020, 7, 22)]


# ---------------- saved outputs ----------------


def _load(path, model):
    if not path.exists():
        pytest.skip(f"{path} not built")
    return [model.model_validate(x) for x in json.loads(path.read_text())]


def _check_spans(rows, sample=40):
    """Re-derive the document text from the (cached) filing and check every sampled span."""
    from validation.text import doc_text

    rows = rows[:sample] + rows[-sample:]
    for r in rows:
        sp = r.span
        try:
            text = doc_text(sp.url)
        except Exception:
            pytest.skip("filing not cached and network unavailable")
        assert text[sp.char_start:sp.char_end] == sp.text, sp.url


def test_disclosed_spans_and_values():
    rows = _load(GROUNDTRUTH / "disclosed.json", DisclosedRatio)
    import re

    for r in rows:
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", r.span.text)]
        assert any(abs(n - r.reported_value) < 1e-9 for n in nums)
        if r.reported_threshold is not None:
            assert any(abs(n - r.reported_threshold) < 1e-9 for n in nums)
        assert len(r.cik) == 10
    _check_spans(rows)


def test_event_spans():
    rows = _load(GROUNDTRUTH / "events.json", CovenantEvent)
    _check_spans(rows)


def test_universe_shape():
    rows = _load(UNIVERSE, UniverseEntry)
    ciks = [r.cik for r in rows]
    assert len(ciks) == len(set(ciks))
    assert all(len(c) == 10 and c.isdigit() for c in ciks)
    for r in rows:
        assert (r.role == "peer") == (r.peer_of is not None)
